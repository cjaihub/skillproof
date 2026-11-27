"""AI document import, skills tests, AI evidence review for assessors, and job-access requests."""
import json
import uuid
from datetime import timedelta
from pathlib import Path

from flask import abort, current_app, flash, g, redirect, render_template, request, url_for

import ai
from core import CATEGORIES, email_verified_required, log, login_required, notify, to_int
from i18n import LANGUAGES, current, gettext as _
from models import (AiReview, DocImport, Evidence, Experience, Skill, SkillTest, User, db, utcnow)

IMPORT_EXT = {"pdf", "png", "jpg", "jpeg", "webp", "docx", "txt"}
RETAKE_AFTER = timedelta(hours=1)


def upload_dir():
    return Path(current_app.config["UPLOAD_FOLDER"])


def job_access_checks(u):
    """Requirements a candidate must meet before asking for job access."""
    return [
        (_("Email confirmed"), u.email_verified),
        (_("At least one independently assessed skill"), bool(u.verified_skills)),
        (_("Profile at least 70% complete"), u.completeness >= 70),
        (_("Report sharing turned on"), u.consent_share),
    ]


def register(app):

    # ------------------------------------------------------------ AI document import

    @app.route("/import", methods=["GET", "POST"])
    @login_required("candidate")
    def import_docs():
        u = g.user
        if request.method == "POST":
            file = request.files.get("file")
            if not file or not file.filename:
                flash(_("Choose a file to upload."), "error")
                return redirect(url_for("import_docs"))
            ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
            if ext not in IMPORT_EXT:
                flash(_("This file type can't be read. Use PDF, Word (.docx), a photo (JPG/PNG) or a text file."), "error")
                return redirect(url_for("import_docs"))
            stored = f"{uuid.uuid4().hex}.{ext}"
            path = upload_dir() / stored
            file.save(path)
            mode, result = ai.import_document(path, u, Path(file.filename).name, LANGUAGES[current()][1])
            imp = DocImport(user_id=u.id, stored_name=stored, original_name=Path(file.filename).name[:255],
                            mode=mode, result_json=json.dumps(result, ensure_ascii=False))
            db.session.add(imp)
            log("document_imported", u.id, f"mode={mode} file={imp.original_name}")
            db.session.commit()
            return redirect(url_for("import_review", iid=imp.id))
        imports = DocImport.query.filter_by(user_id=u.id).order_by(DocImport.created_at.desc()).limit(10).all()
        return render_template("candidate/import.html", u=u, imports=imports, ai_on=ai.enabled())

    def own_import(iid):
        return DocImport.query.filter_by(id=iid, user_id=g.user.id).first_or_404()

    @app.route("/import/<int:iid>")
    @login_required("candidate")
    def import_review(iid):
        imp = own_import(iid)
        r = json.loads(imp.result_json or "{}")
        existing = {s.name.lower() for s in g.user.skills}
        return render_template("candidate/import_review.html", imp=imp, r=r, u=g.user, existing=existing)

    @app.route("/import/<int:iid>/apply", methods=["POST"])
    @login_required("candidate")
    def import_apply(iid):
        imp, u, f = own_import(iid), g.user, request.form
        if imp.status != "ready":
            flash(_("These suggestions were already used."), "info")
            return redirect(url_for("import_docs"))
        r = json.loads(imp.result_json or "{}")
        changed = []
        for field in ("headline", "location", "bio"):
            if f.get(f"use_{field}") and r.get(field):
                setattr(u, field, r[field][:2000 if field == "bio" else 160])
                changed.append(field)
        for i, c in enumerate(r.get("corrections", [])):
            if f.get(f"corr_{i}") and c.get("field") in ("headline", "location", "bio"):
                setattr(u, c["field"], (c.get("suggested_value") or "")[:2000])
                changed.append(c["field"])
        added_exp = 0
        for i, e in enumerate(r.get("experiences", [])):
            if f.get(f"exp_{i}") and e.get("title"):
                db.session.add(Experience(user_id=u.id, title=e["title"][:160], organisation=(e.get("organisation") or "")[:160],
                                          country=(e.get("country") or "")[:80], start_year=e.get("start_year"),
                                          end_year=e.get("end_year"), description=e.get("description") or ""))
                added_exp += 1
        new_skills = []
        names = {s.name.lower() for s in u.skills}
        for i, s in enumerate(r.get("skills", [])):
            if f.get(f"skill_{i}") and s.get("name") and s["name"].lower() not in names:
                sk = Skill(user_id=u.id, name=s["name"][:120],
                           category=s.get("category") if s.get("category") in CATEGORIES else "Other",
                           claimed_level=to_int(s.get("level"), 3, 1, 5), years=to_int(s.get("years"), 0, 0, 60),
                           description=(s.get("evidence_note") or "")[:1000])
                db.session.add(sk)
                new_skills.append(sk)
                names.add(sk.name.lower())
        db.session.flush()
        if f.get("save_evidence") and r.get("document_type") != "id_document":
            kind = {"cv": "other", "certificate": "certificate", "reference_letter": "reference",
                    "work_sample": "work_sample"}.get(r.get("document_type"), "other")
            db.session.add(Evidence(user_id=u.id, skill_id=new_skills[0].id if len(new_skills) == 1 else None,
                                    title=imp.original_name[:160], kind=kind, stored_name=imp.stored_name,
                                    original_name=imp.original_name, description=(r.get("summary") or "")[:2000]))
        else:
            (upload_dir() / imp.stored_name).unlink(missing_ok=True)
        imp.status = "applied"
        log("import_applied", u.id, f"fields={','.join(changed)} skills={len(new_skills)} experience={added_exp}")
        db.session.commit()
        flash(_("Profile updated: {skills} skills and {exp} jobs added.", skills=len(new_skills), exp=added_exp), "success")
        return redirect(url_for("skills") if new_skills else url_for("profile"))

    @app.route("/import/<int:iid>/discard", methods=["POST"])
    @login_required("candidate")
    def import_discard(iid):
        imp = own_import(iid)
        if imp.status == "ready":
            (upload_dir() / imp.stored_name).unlink(missing_ok=True)
        imp.status = "discarded"
        db.session.commit()
        flash(_("Suggestions discarded and the file deleted."), "info")
        return redirect(url_for("import_docs"))

    # ------------------------------------------------------------ skills test

    @app.route("/skills/<int:sid>/test", methods=["GET", "POST"])
    @login_required("candidate")
    def skill_test(sid):
        s = Skill.query.filter_by(id=sid, user_id=g.user.id).first_or_404()
        if s.status in ("pending", "verified"):
            flash(_("This skill is already in assessment or verified."), "info")
            return redirect(url_for("skill_detail", sid=sid))
        open_test = next((t for t in s.tests if not t.submitted_at), None)
        if request.method == "POST":
            if not open_test or str(open_test.id) != request.form.get("test_id"):
                flash(_("This test has expired. Please start again."), "error")
                return redirect(url_for("skill_test", sid=sid))
            qs = json.loads(open_test.questions_json)
            answers, score = {}, 0
            for i, q in enumerate(qs["mcq"]):
                a = to_int(request.form.get(f"q{i}"), -1)
                answers[f"q{i}"] = a
                score += int(a == q["correct_index"])
            for i, _q in enumerate(qs["short_questions"]):
                answers[f"s{i}"] = request.form.get(f"s{i}", "").strip()[:3000]
            if any(len(answers[f"s{i}"]) < 20 for i in range(len(qs["short_questions"]))):
                flash(_("Please answer each written question in a few sentences."), "error")
                return render_template("candidate/skill_test.html", s=s, t=open_test, qs=qs, answers=answers)
            open_test.answers_json = json.dumps(answers, ensure_ascii=False)
            open_test.mcq_score, open_test.mcq_total, open_test.submitted_at = score, len(qs["mcq"]), utcnow()
            log("skill_test_submitted", g.user.id, f"skill={s.id} score={score}/{len(qs['mcq'])}")
            db.session.commit()
            flash(_("Test submitted: {score}/{total} multiple-choice answers correct. Now complete the practical task.",
                    score=score, total=len(qs["mcq"])), "success")
            return redirect(url_for("skill_detail", sid=sid) + "#practical")
        if not open_test:
            last = next((t for t in s.tests if t.submitted_at), None)
            if last and utcnow() - last.submitted_at < RETAKE_AFTER and request.args.get("retake"):
                flash(_("You can retake the test one hour after your last attempt."), "info")
                return redirect(url_for("skill_detail", sid=sid))
            if last and not request.args.get("retake"):
                return redirect(url_for("skill_detail", sid=sid))
            source, qs = ai.build_test(s, LANGUAGES[current()][1])
            open_test = SkillTest(skill_id=s.id, user_id=g.user.id, source=source,
                                  questions_json=json.dumps(qs, ensure_ascii=False))
            db.session.add(open_test)
            db.session.commit()
        return render_template("candidate/skill_test.html", s=s, t=open_test, qs=json.loads(open_test.questions_json),
                               answers={})

    # ------------------------------------------------------------ AI evidence review (assessors)

    @app.route("/review/<int:sid>/ai", methods=["POST"])
    @login_required("assessor", "admin")
    def review_ai(sid):
        s = db.get_or_404(Skill, sid)
        if s.user_id == g.user.id or (g.user.role != "admin" and s.status != "pending"):
            abort(403)
        try:
            result = ai.review_evidence(s, upload_dir())
        except ai.AIUnavailable as e:
            flash(_("AI review is not available right now ({reason}). You can assess manually as usual.", reason=str(e)), "error")
            return redirect(url_for("review", sid=sid))
        db.session.add(AiReview(skill_id=s.id, requested_by=g.user.id, model=ai.MODEL,
                                result_json=json.dumps(result, ensure_ascii=False)))
        log("ai_review_generated", s.user_id, f"skill={s.id}")
        db.session.commit()
        flash(_("AI review ready. It is advisory: you make the decision."), "success")
        return redirect(url_for("review", sid=sid) + "#ai-review")

    # ------------------------------------------------------------ job access

    @app.route("/job-access", methods=["GET", "POST"])
    @login_required("candidate")
    @email_verified_required
    def job_access():
        u = g.user
        checks = job_access_checks(u)
        if request.method == "POST":
            if u.job_access in ("requested", "granted"):
                flash(_("Your request is already with the SkillProof team."), "info")
            elif not all(ok for _label, ok in checks):
                flash(_("Complete all the requirements before requesting job access."), "error")
            else:
                u.job_access, u.job_access_at = "requested", utcnow()
                u.job_access_note = request.form.get("note", "").strip()[:500]
                log("job_access_requested", u.id)
                for admin in User.query.filter_by(role="admin", status="active"):
                    notify(admin.id, f"Job access requested by {u.full_name}", url_for("admin_verifications"), "warning")
                db.session.commit()
                flash(_("Request sent. An administrator will review your verified skills and grant access to jobs."), "success")
            return redirect(url_for("job_access"))
        return render_template("candidate/job_access.html", u=u, checks=checks)

    @app.route("/admin/users/<int:uid>/job-access", methods=["POST"])
    @login_required("admin")
    def admin_job_access(uid):
        u = db.get_or_404(User, uid)
        decision = request.form.get("decision")
        note = request.form.get("note", "").strip()[:500]
        if u.role != "candidate" or decision not in ("granted", "declined", "revoked"):
            abort(400)
        if decision != "granted" and len(note) < 5:
            flash(_("Give the candidate a reason (at least 5 characters)."), "error")
            return redirect(request.referrer or url_for("admin_verifications"))
        u.job_access = "none" if decision == "revoked" else decision
        u.job_access_note, u.job_access_at = note, utcnow()
        log("job_access_" + decision, u.id, note)
        notify(u.id, ("You now have access to jobs on SkillProof. Browse openings that match your skills."
                      if decision == "granted" else f"Your job access request was not approved: {note}"),
               url_for("jobs") if decision == "granted" else url_for("job_access"),
               "success" if decision == "granted" else "warning")
        db.session.commit()
        flash(f"{u.full_name}: job access {decision}.", "success")
        return redirect(request.referrer or url_for("admin_verifications"))
