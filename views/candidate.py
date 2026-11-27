"""Candidate area: dashboard, profile, skills, evidence, report, consent, appeals."""
import secrets
import uuid
from pathlib import Path

from flask import abort, current_app, flash, g, redirect, render_template, request, send_from_directory, url_for

from core import (ALLOWED_EXT, CATEGORIES, can_view_evidence, daily_counts, email_verified_required, log,
                  login_required, notify, task_for, to_int)
from i18n import gettext as _
from models import (EVIDENCE_KINDS, Appeal, Assessment, AuditLog, Evidence, Experience, Skill, User, db,
                    utcnow)

VIEW_ACTIONS = ("profile_view_employer", "profile_view_link")


def register(app):

    @app.route("/dashboard")
    @login_required()
    def dashboard():
        role = g.user.role
        if role == "assessor":
            return redirect(url_for("review_queue"))
        if role == "employer":
            return redirect(url_for("employer_dashboard"))
        if role == "admin":
            return redirect(url_for("admin"))
        u = g.user
        views_q = AuditLog.query.filter(AuditLog.subject_user_id == u.id, AuditLog.action.in_(VIEW_ACTIONS))
        labels, views = daily_counts(AuditLog.created_at, 30, (AuditLog.subject_user_id == u.id,
                                                               AuditLog.action.in_(VIEW_ACTIONS)))
        steps = [
            ("Confirm your email", u.email_verified, url_for("account")),
            ("Complete your profile", bool(u.headline and len(u.bio or "") >= 80), url_for("profile")),
            ("Add your skills", bool(u.skills), url_for("skill_new")),
            ("Upload evidence", bool(u.evidence), url_for("evidence_list")),
            ("Request an assessment", any(s.status != "self_declared" for s in u.skills),
             url_for("skill_detail", sid=u.skills[0].id) if u.skills else url_for("skill_new")),
            ("Share your report", u.consent_share, url_for("report")),
        ]
        employer_views = views_q.filter(AuditLog.action == "profile_view_employer").count()
        kpis = dict(skills=len(u.skills), verified=len(u.verified_skills), evidence=len(u.evidence),
                    views=views_q.count(), employer_views=employer_views,
                    pending=sum(s.status == "pending" for s in u.skills))
        appeals = Appeal.query.filter_by(user_id=u.id).order_by(Appeal.created_at.desc()).all()
        return render_template("candidate/dashboard.html", u=u, steps=steps, kpis=kpis, appeals=appeals,
                               chart=dict(labels=labels, data=views),
                               activity=u.notifications.limit(6).all())

    # ---- profile & experience

    @app.route("/profile", methods=["GET", "POST"])
    @login_required("candidate")
    def profile():
        u = g.user
        if request.method == "POST":
            f = request.form
            name = " ".join(f.get("full_name", "").split())
            if len(name) >= 2:
                u.full_name = name[:120]
            u.headline = f.get("headline", "").strip()[:160]
            u.location = f.get("location", "").strip()[:120]
            u.bio = f.get("bio", "").strip()[:2000]
            db.session.commit()
            flash("Profile saved.", "success")
            return redirect(url_for("profile"))
        return render_template("candidate/profile.html", u=u)

    @app.route("/experience", methods=["POST"])
    @login_required("candidate")
    def experience_add():
        f = request.form
        if not f.get("title", "").strip():
            flash("Job title is required.", "error")
        else:
            db.session.add(Experience(
                user_id=g.user.id, title=f["title"].strip()[:160], organisation=f.get("organisation", "").strip()[:160],
                country=f.get("country", "").strip()[:80],
                start_year=to_int(f.get("start_year"), None, 1950, 2100),
                end_year=to_int(f.get("end_year"), None, 1950, 2100),
                description=f.get("description", "").strip()))
            db.session.commit()
            flash("Experience added.", "success")
        return redirect(url_for("profile") + "#experience")

    @app.route("/experience/<int:eid>/delete", methods=["POST"])
    @login_required("candidate")
    def experience_delete(eid):
        e = Experience.query.filter_by(id=eid, user_id=g.user.id).first_or_404()
        db.session.delete(e)
        db.session.commit()
        flash("Experience removed.", "info")
        return redirect(url_for("profile") + "#experience")

    @app.route("/consent", methods=["POST"])
    @login_required("candidate")
    @email_verified_required
    def consent():
        u = g.user
        give = request.form.get("share") == "1"
        u.consent_share = give
        u.consent_at = utcnow() if give else None
        if request.form.get("rotate") == "1":
            u.share_token = secrets.token_urlsafe(16)
        log("consent_given" if give else "consent_withdrawn", u.id)
        db.session.commit()
        flash("Your profile is now shared with employers and via your link." if give
              else "Sharing turned off. Employers and your link can no longer see your profile.", "success")
        return redirect(request.referrer or url_for("report"))

    # ---- skills

    def skill_from_form(s, f):
        s.name = " ".join(f.get("name", "").split())[:120]
        s.category = f.get("category") if f.get("category") in CATEGORIES else "Other"
        s.claimed_level = to_int(f.get("claimed_level"), 3, 1, 5)
        s.years = to_int(f.get("years"), 0, 0, 60)
        s.description = f.get("description", "").strip()[:1000]

    def own_skill(sid):
        return Skill.query.filter_by(id=sid, user_id=g.user.id).first_or_404()

    @app.route("/skills")
    @login_required("candidate")
    def skills():
        return render_template("candidate/skills.html", u=g.user)

    @app.route("/skills/new", methods=["GET", "POST"])
    @login_required("candidate")
    def skill_new():
        if request.method == "POST":
            s = Skill(user_id=g.user.id)
            skill_from_form(s, request.form)
            if not s.name:
                flash("Skill name is required.", "error")
                return render_template("candidate/skill_form.html", s=s)
            db.session.add(s)
            db.session.commit()
            flash(f"“{s.name}” added as a self-declared skill. Add evidence and request an assessment to verify it.", "success")
            return redirect(url_for("skill_detail", sid=s.id))
        return render_template("candidate/skill_form.html", s=None)

    @app.route("/skills/<int:sid>")
    @login_required("candidate")
    def skill_detail(sid):
        s = own_skill(sid)
        return render_template("candidate/skill_detail.html", s=s, task=task_for(s))

    @app.route("/skills/<int:sid>/edit", methods=["GET", "POST"])
    @login_required("candidate")
    def skill_edit(sid):
        s = own_skill(sid)
        if s.status in ("pending", "verified"):
            flash("This skill is under or past assessment, so it can't be edited. "
                  "Add a new skill or appeal the decision instead.", "info")
            return redirect(url_for("skill_detail", sid=sid))
        if request.method == "POST":
            skill_from_form(s, request.form)
            if not s.name:
                flash("Skill name is required.", "error")
                return render_template("candidate/skill_form.html", s=s)
            db.session.commit()
            flash("Skill updated.", "success")
            return redirect(url_for("skill_detail", sid=sid))
        return render_template("candidate/skill_form.html", s=s)

    @app.route("/skills/<int:sid>/delete", methods=["POST"])
    @login_required("candidate")
    def skill_delete(sid):
        s = own_skill(sid)
        db.session.delete(s)
        db.session.commit()
        flash("Skill removed.", "info")
        return redirect(url_for("skills"))

    @app.route("/skills/<int:sid>/request", methods=["POST"])
    @login_required("candidate")
    @email_verified_required
    def skill_request(sid):
        s = own_skill(sid)
        resp = request.form.get("task_response", "").strip()
        test = next((t for t in s.tests if t.submitted_at), None)
        if s.status not in ("self_declared", "not_verified"):
            flash("This skill is already awaiting or has passed assessment.", "info")
        elif not test:
            flash(_("Take the skills test first, then submit the practical task."), "error")
        elif len(resp) < 50:
            flash("Please give a fuller answer to the practical task (at least 50 characters).", "error")
        else:
            s.task_response = resp[:5000]
            s.status = "pending"
            s.requested_at = utcnow()
            log("assessment_requested", g.user.id, f"skill={s.id}")
            for a in User.query.filter_by(role="assessor", status="active"):
                notify(a.id, f"New assessment request: {s.name} ({s.category})", url_for("review", sid=s.id))
            db.session.commit()
            flash("Assessment requested. An assessor will review your evidence and task.", "success")
        return redirect(url_for("skill_detail", sid=sid))

    # ---- evidence

    @app.route("/evidence", methods=["GET", "POST"])
    @login_required("candidate")
    def evidence_list():
        u = g.user
        if request.method == "POST":
            f = request.form
            file = request.files.get("file")
            link = f.get("link", "").strip()
            title = f.get("title", "").strip()
            back = f.get("back") if (f.get("back") or "").startswith("/skills/") else url_for("evidence_list")
            if not title:
                flash("Please give the evidence a title.", "error")
                return redirect(back)
            if link and not link.startswith(("http://", "https://")):
                flash("Links must start with http:// or https://", "error")
                return redirect(back)
            if not (file and file.filename) and not link:
                flash("Upload a file or add a link.", "error")
                return redirect(back)
            ev = Evidence(user_id=u.id, title=title[:160],
                          kind=f.get("kind") if f.get("kind") in EVIDENCE_KINDS else "other",
                          description=f.get("description", "").strip()[:2000], link=link[:500])
            sid = to_int(f.get("skill_id"), None)
            if sid and Skill.query.filter_by(id=sid, user_id=u.id).first():
                ev.skill_id = sid
            if file and file.filename:
                ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
                if ext not in ALLOWED_EXT:
                    flash("File type not allowed. Use PDF, image, Word, text or zip.", "error")
                    return redirect(back)
                ev.stored_name = f"{uuid.uuid4().hex}.{ext}"
                ev.original_name = Path(file.filename).name[:255]
                file.save(Path(current_app.config["UPLOAD_FOLDER"]) / ev.stored_name)
            db.session.add(ev)
            db.session.commit()
            flash("Evidence saved securely.", "success")
            return redirect(back)
        return render_template("candidate/evidence.html", u=u, preselect=to_int(request.args.get("skill"), None))

    @app.route("/evidence/<int:eid>/delete", methods=["POST"])
    @login_required("candidate")
    def evidence_delete(eid):
        ev = Evidence.query.filter_by(id=eid, user_id=g.user.id).first_or_404()
        if ev.stored_name:
            (Path(current_app.config["UPLOAD_FOLDER"]) / ev.stored_name).unlink(missing_ok=True)
        db.session.delete(ev)
        db.session.commit()
        flash("Evidence deleted.", "info")
        return redirect(url_for("evidence_list"))

    @app.route("/evidence/<int:eid>/file")
    @login_required()
    def evidence_file(eid):
        ev = db.get_or_404(Evidence, eid)
        if not ev.stored_name:
            abort(404)
        if not can_view_evidence(g.user, ev):
            abort(403)
        if g.user.id != ev.user_id:
            log("evidence_viewed", ev.user_id, f"evidence={ev.id}")
            db.session.commit()
        return send_from_directory(current_app.config["UPLOAD_FOLDER"], ev.stored_name,
                                   as_attachment=True, download_name=ev.original_name)

    # ---- report, appeals, access log

    @app.route("/report")
    @login_required("candidate")
    def report():
        return render_template("candidate/report.html", u=g.user)

    @app.route("/assessments/<int:aid>/appeal", methods=["POST"])
    @login_required("candidate")
    def appeal(aid):
        a = db.get_or_404(Assessment, aid)
        if a.skill.user_id != g.user.id:
            abort(403)
        reason = request.form.get("reason", "").strip()
        if len(reason) < 20:
            flash("Please explain the reason for your appeal (at least 20 characters).", "error")
        elif any(ap.status == "open" for ap in a.appeals):
            flash("You already have an open appeal for this assessment.", "info")
        else:
            db.session.add(Appeal(assessment_id=a.id, user_id=g.user.id, reason=reason[:3000]))
            log("appeal_submitted", g.user.id, f"assessment={a.id}")
            for admin in User.query.filter_by(role="admin", status="active"):
                notify(admin.id, f"New appeal from {g.user.full_name} on {a.skill.name}",
                       url_for("admin_appeals"), "warning")
            db.session.commit()
            flash("Appeal submitted. An administrator will review it and a different assessor "
                  "will reassess if it is upheld.", "success")
        return redirect(url_for("skill_detail", sid=a.skill_id))

    @app.route("/my-access-log")
    @login_required("candidate")
    def my_access_log():
        entries = (AuditLog.query.filter(AuditLog.subject_user_id == g.user.id)
                   .order_by(AuditLog.created_at.desc()).limit(200).all())
        return render_template("candidate/access_log.html", entries=entries)
