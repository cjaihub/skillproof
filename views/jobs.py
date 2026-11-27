"""Jobs: employers post, admins approve, job-ready candidates apply, employers track applicants."""
from flask import abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import or_

import ai
from core import CATEGORIES, log, login_required, notify, safe_next, to_int
from i18n import gettext as _
from models import APPLICATION_STATUSES, JOB_STATUSES, JOB_TYPES, Application, Job, User, db, utcnow

EMPLOYER_STATUS_FLOW = ("applied", "shortlisted", "interview", "offered", "hired", "declined")


def job_from_form(job, f):
    job.title = " ".join(f.get("title", "").split())[:160]
    job.category = f.get("category") if f.get("category") in CATEGORIES else "Other"
    job.location = f.get("location", "").strip()[:120]
    job.remote = bool(f.get("remote"))
    job.job_type = f.get("job_type") if f.get("job_type") in JOB_TYPES else "full_time"
    job.salary = f.get("salary", "").strip()[:120]
    job.description = f.get("description", "").strip()[:5000]
    job.required_skills = ", ".join(s.strip() for s in f.get("required_skills", "").split(",") if s.strip())[:500]
    job.min_level = to_int(f.get("min_level"), 3, 1, 5)


def register(app):

    @app.context_processor
    def job_constants():
        return dict(JOB_TYPES=JOB_TYPES, JOB_STATUSES=JOB_STATUSES, APPLICATION_STATUSES=APPLICATION_STATUSES)

    # ------------------------------------------------------------ employer

    @app.route("/employer/jobs")
    @login_required("employer")
    def employer_jobs():
        jobs = Job.query.filter_by(employer_id=g.user.id).order_by(Job.created_at.desc()).all()
        return render_template("jobs/employer_jobs.html", jobs=jobs)

    @app.route("/employer/jobs/new", methods=["GET", "POST"])
    @app.route("/employer/jobs/<int:jid>/edit", methods=["GET", "POST"])
    @login_required("employer")
    def job_edit(jid=None):
        job = Job.query.filter_by(id=jid, employer_id=g.user.id).first_or_404() if jid else Job(employer_id=g.user.id)
        if request.method == "POST":
            job_from_form(job, request.form)
            if len(job.title) < 3 or len(job.description) < 40:
                flash(_("Add a job title and a description of at least 40 characters."), "error")
                return render_template("jobs/job_form.html", job=job)
            job.status, job.review_note = "pending", ""  # every new or edited post is checked by an admin
            if not jid:
                db.session.add(job)
            db.session.flush()
            log("job_submitted", None, f"job={job.id} title={job.title}")
            for admin in User.query.filter_by(role="admin", status="active"):
                notify(admin.id, f"Job post awaiting approval: {job.title} ({g.user.organisation})",
                       url_for("admin_jobs"), "warning")
            db.session.commit()
            flash(_("Job submitted. It will be visible to candidates once an administrator approves it."), "success")
            return redirect(url_for("employer_job", jid=job.id))
        return render_template("jobs/job_form.html", job=job if jid else None)

    @app.route("/employer/jobs/<int:jid>")
    @login_required("employer", "admin")
    def employer_job(jid):
        job = db.get_or_404(Job, jid)
        if g.user.role == "employer" and job.employer_id != g.user.id:
            abort(404)
        status = request.args.get("status", "")
        apps = [a for a in job.applications if a.status != "withdrawn" and (not status or a.status == status)]
        apps.sort(key=lambda a: (-a.match, a.created_at))
        return render_template("jobs/employer_job.html", job=job, apps=apps, status=status, flow=EMPLOYER_STATUS_FLOW)

    @app.route("/employer/jobs/<int:jid>/close", methods=["POST"])
    @login_required("employer")
    def job_close(jid):
        job = Job.query.filter_by(id=jid, employer_id=g.user.id).first_or_404()
        job.status = "closed" if job.status != "closed" else "pending"
        log("job_" + ("closed" if job.status == "closed" else "reopened"), None, f"job={job.id}")
        db.session.commit()
        flash(_("Job closed.") if job.status == "closed" else _("Job sent for re-approval."), "info")
        return redirect(url_for("employer_job", jid=jid))

    @app.route("/applications/<int:aid>/status", methods=["POST"])
    @login_required("employer")
    def application_status(aid):
        a = db.get_or_404(Application, aid)
        if a.job.employer_id != g.user.id:
            abort(404)
        new = request.form.get("status")
        if new not in EMPLOYER_STATUS_FLOW or a.status == "withdrawn":
            abort(400)
        if new != a.status:
            a.status, a.updated_at = new, utcnow()
            log("application_" + new, a.candidate_id, f"job={a.job_id}")
            notify(a.candidate_id, f"{a.job.employer.organisation or 'An employer'}: your application for "
                                   f"“{a.job.title}” is now {APPLICATION_STATUSES[new].lower()}.",
                   url_for("my_applications"), "success" if new in ("shortlisted", "interview", "offered", "hired") else "info")
            db.session.commit()
        return redirect(safe_next(request.form.get("next"), url_for("employer_job", jid=a.job_id)))

    # ------------------------------------------------------------ admin

    @app.route("/admin/jobs")
    @login_required("admin")
    def admin_jobs():
        status = request.args.get("status", "")
        q = Job.query
        if status in JOB_STATUSES:
            q = q.filter_by(status=status)
        jobs = q.order_by(Job.status != "pending", Job.created_at.desc()).all()
        counts = {s: Job.query.filter_by(status=s).count() for s in JOB_STATUSES}
        hires = Application.query.filter_by(status="hired").count()
        return render_template("jobs/admin_jobs.html", jobs=jobs, status=status, counts=counts, hires=hires)

    @app.route("/admin/jobs/<int:jid>/review", methods=["POST"])
    @login_required("admin")
    def admin_job_review(jid):
        job = db.get_or_404(Job, jid)
        decision = request.form.get("decision")
        note = request.form.get("note", "").strip()[:500]
        if decision not in ("open", "rejected"):
            abort(400)
        if decision == "rejected" and len(note) < 5:
            flash(_("Give the employer a reason (at least 5 characters)."), "error")
            return redirect(url_for("admin_jobs"))
        job.status, job.review_note, job.approved_by, job.approved_at = decision, note, g.user.id, utcnow()
        log("job_" + ("approved" if decision == "open" else "rejected"), job.employer_id, f"job={job.id}")
        notify(job.employer_id, (f"Your job “{job.title}” is approved and visible to job-ready candidates."
                                 if decision == "open" else f"Your job “{job.title}” was not approved: {note}"),
               url_for("employer_job", jid=job.id), "success" if decision == "open" else "warning")
        if decision == "open":  # let well-matched job-ready candidates know
            for c in User.query.filter_by(role="candidate", status="active", job_access="granted"):
                if ai.match_score(job, c) >= 60:
                    notify(c.id, f"New job matching your skills: {job.title}", url_for("job_detail", jid=job.id), "success")
        db.session.commit()
        flash(_("Job approved and published.") if decision == "open" else _("Job rejected."), "success")
        return redirect(url_for("admin_jobs"))

    # ------------------------------------------------------------ candidate

    @app.route("/jobs")
    @login_required("candidate", "admin")
    def jobs():
        q = request.args.get("q", "").strip()
        cat = request.args.get("category", "")
        jtype = request.args.get("type", "")
        query = Job.query.filter_by(status="open")
        if q:
            like = f"%{q}%"
            query = query.filter(or_(Job.title.ilike(like), Job.description.ilike(like), Job.required_skills.ilike(like),
                                     Job.location.ilike(like)))
        if cat in CATEGORIES:
            query = query.filter_by(category=cat)
        if jtype in JOB_TYPES:
            query = query.filter_by(job_type=jtype)
        rows = query.order_by(Job.approved_at.desc()).all()
        me = g.user
        scored = [(j, ai.match_score(j, me) if me.role == "candidate" else None) for j in rows]
        if me.role == "candidate":
            scored.sort(key=lambda x: -x[1])
        applied = {a.job_id: a for a in Application.query.filter_by(candidate_id=me.id)}
        return render_template("jobs/jobs.html", scored=scored, q=q, cat=cat, jtype=jtype, applied=applied)

    @app.route("/jobs/<int:jid>", methods=["GET", "POST"])
    @login_required("candidate", "admin")
    def job_detail(jid):
        job = db.get_or_404(Job, jid)
        if job.status != "open" and g.user.role != "admin":
            abort(404)
        me = g.user
        existing = Application.query.filter_by(job_id=job.id, candidate_id=me.id).first()
        score = ai.match_score(job, me) if me.role == "candidate" else None
        if request.method == "POST":
            if me.role != "candidate":
                abort(403)
            if me.job_access != "granted":
                flash(_("You need job access from an administrator before applying."), "error")
            elif not me.consent_share:
                flash(_("Turn on report sharing first, so the employer can see your verified skills."), "error")
            elif existing and existing.status != "withdrawn":
                flash(_("You've already applied for this job."), "info")
            else:
                note = request.form.get("cover_note", "").strip()[:2000]
                if existing:
                    existing.status, existing.cover_note, existing.match, existing.updated_at = "applied", note, score, utcnow()
                else:
                    db.session.add(Application(job_id=job.id, candidate_id=me.id, cover_note=note, match=score))
                log("job_applied", me.id, f"job={job.id} match={score}")
                notify(job.employer_id, f"New applicant for “{job.title}”: {me.full_name} ({score}% skills match)",
                       url_for("employer_job", jid=job.id), "info")
                db.session.commit()
                flash(_("Application sent! The employer can now see your competency report."), "success")
            return redirect(url_for("job_detail", jid=jid))
        mine = [s.name.lower() for s in me.verified_skills]
        have = {r for r in job.skills_list if any(r.lower() in n or n in r.lower() for n in mine)}
        return render_template("jobs/job_detail.html", job=job, existing=existing, score=score, have=have)

    @app.route("/my-applications")
    @login_required("candidate")
    def my_applications():
        apps = Application.query.filter_by(candidate_id=g.user.id).order_by(Application.updated_at.desc()).all()
        return render_template("jobs/my_applications.html", apps=apps)

    @app.route("/applications/<int:aid>/withdraw", methods=["POST"])
    @login_required("candidate")
    def application_withdraw(aid):
        a = Application.query.filter_by(id=aid, candidate_id=g.user.id).first_or_404()
        if a.status not in ("hired", "withdrawn"):
            a.status, a.updated_at = "withdrawn", utcnow()
            log("application_withdrawn", g.user.id, f"job={a.job_id}")
            db.session.commit()
            flash(_("Application withdrawn."), "info")
        return redirect(url_for("my_applications"))
