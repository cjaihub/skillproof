"""SkillProof: digital skills recognition and validation platform (prototype)."""
import json
import os
import secrets
import uuid
from functools import wraps
from pathlib import Path

from dotenv import load_dotenv
from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   send_from_directory, session, url_for, Response)
from sqlalchemy import func, or_

from models import (CRITERIA, EVIDENCE_KINDS, LEVELS, PASS_MARK, ROLES, SKILL_STATUSES,
                    Appeal, Assessment, AuditLog, Evidence, Experience, Skill, User, db,
                    utcnow)

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
ALLOWED_EXT = {"pdf", "png", "jpg", "jpeg", "doc", "docx", "txt", "zip"}

PRACTICAL_TASKS = {
    "Software development": "Share a link to code you wrote (GitHub, GitLab or a zip upload) and explain in 150-300 words: what problem it solves, one design decision you made and why, and how you tested it.",
    "IT support & networking": "Describe step by step how you would diagnose an office where 10 computers suddenly cannot reach the internet but the router shows as online. Include the tools and commands you would use.",
    "Healthcare": "Describe a real case you handled (no patient names): the situation, the actions you took, the protocols you followed and the outcome.",
    "Teaching & training": "Outline a 45-minute lesson plan on a topic you teach: learning objectives, activities, and how you check learners understood.",
    "Trades & vocational": "Upload photos or a short video of work you completed and describe the materials, tools, safety steps and time it took.",
    "Business & finance": "Describe a budget, report or process you were responsible for, the figures or scale involved, and a problem you solved.",
}
DEFAULT_TASK = "Describe a piece of work that demonstrates this skill: what you did, the tools or methods you used, the result, and how someone could check it. Add links where possible."


def _secret_key():
    """Use SECRET_KEY from the environment; otherwise keep a generated one in a local file
    so sessions survive restarts and work across several server workers."""
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    path = BASE_DIR / ".secret_key"
    if not path.exists():
        path.write_text(secrets.token_hex(32))
        path.chmod(0o600)
    return path.read_text().strip()


def create_app():
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=_secret_key(),
        SQLALCHEMY_DATABASE_URI=os.environ.get("DATABASE_URL", f"sqlite:///{BASE_DIR / 'skillproof.db'}"),
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
        UPLOAD_FOLDER=os.environ.get("UPLOAD_FOLDER", str(BASE_DIR / "uploads")),
        MAX_CONTENT_LENGTH=10 * 1024 * 1024,  # 10 MB per upload
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "0") == "1",
    )
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
    db.init_app(app)
    with app.app_context():
        db.create_all()
    register_routes(app)
    return app


# ---------------------------------------------------------------- helpers

def log(action, subject_user_id=None, detail=""):
    db.session.add(AuditLog(actor_id=g.user.id if g.get("user") else None, action=action,
                            subject_user_id=subject_user_id, detail=detail[:500]))


def login_required(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if not g.user:
                flash("Please log in to continue.", "info")
                return redirect(url_for("login", next=request.path))
            if roles and g.user.role not in roles:
                abort(403)
            return fn(*a, **kw)
        return wrapper
    return deco


def to_int(value, default=0, lo=None, hi=None):
    try:
        v = int(value)
    except (TypeError, ValueError):
        return default
    if lo is not None:
        v = max(lo, v)
    if hi is not None:
        v = min(hi, v)
    return v


def can_view_evidence(user, ev):
    """Evidence is private: owner, assessors and admins only. Never employers."""
    return user and (user.id == ev.user_id or user.role in ("assessor", "admin"))


def task_for(skill):
    return PRACTICAL_TASKS.get(skill.category, DEFAULT_TASK)


# ---------------------------------------------------------------- routes

def register_routes(app):

    @app.before_request
    def load_user_and_csrf():
        uid = session.get("uid")
        g.user = db.session.get(User, uid) if uid else None
        if g.user and not g.user.is_active:
            session.clear()
            g.user = None
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(32)
        if request.method == "POST":
            if request.form.get("csrf") != session["csrf"]:
                abort(400, "Invalid form token. Please reload the page and try again.")

    @app.context_processor
    def inject():
        return dict(current_user=g.get("user"), csrf_token=session.get("csrf"),
                    LEVELS=LEVELS, SKILL_STATUSES=SKILL_STATUSES, CRITERIA=CRITERIA,
                    EVIDENCE_KINDS=EVIDENCE_KINDS, PASS_MARK=PASS_MARK, now=utcnow(),
                    CATEGORIES=list(PRACTICAL_TASKS) + ["Other"])

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("error.html", code=403, message="You do not have access to this page."), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template("error.html", code=404, message="Page not found."), 404

    @app.errorhandler(413)
    def too_large(e):
        flash("That file is too large. The limit is 10 MB.", "error")
        return redirect(request.referrer or url_for("evidence_list"))

    # ---- public

    @app.route("/")
    def index():
        stats = dict(
            candidates=User.query.filter_by(role="candidate").count(),
            verified=Skill.query.filter_by(status="verified").count(),
            employers=User.query.filter_by(role="employer").count(),
        )
        return render_template("index.html", stats=stats)

    @app.route("/privacy")
    def privacy():
        return render_template("privacy.html")

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            f = request.form
            email = f.get("email", "").strip().lower()
            name = f.get("full_name", "").strip()
            pw = f.get("password", "")
            role = f.get("role") if f.get("role") in ("candidate", "employer") else "candidate"
            errors = []
            if not name:
                errors.append("Please enter your name.")
            if "@" not in email or "." not in email.split("@")[-1]:
                errors.append("Please enter a valid email address.")
            if len(pw) < 8:
                errors.append("Password must be at least 8 characters.")
            if pw != f.get("confirm"):
                errors.append("Passwords do not match.")
            if not f.get("agree"):
                errors.append("You need to accept the privacy notice to create an account.")
            if User.query.filter_by(email=email).first():
                errors.append("An account with this email already exists.")
            if errors:
                for e in errors:
                    flash(e, "error")
                return render_template("register.html", form=f)
            u = User(full_name=name, email=email, role=role,
                     organisation=f.get("organisation", "").strip())
            u.set_password(pw)
            db.session.add(u)
            db.session.flush()
            g.user = u
            log("register", u.id, f"role={role}")
            db.session.commit()
            session.clear()
            session["uid"] = u.id
            flash("Welcome to SkillProof! Your account is ready.", "success")
            return redirect(url_for("dashboard"))
        return render_template("register.html", form={})

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            u = User.query.filter_by(email=request.form.get("email", "").strip().lower()).first()
            if u and u.is_active and u.check_password(request.form.get("password", "")):
                session.clear()
                session["uid"] = u.id
                nxt = request.args.get("next", "")
                return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("dashboard"))
            flash("Incorrect email or password.", "error")
        return render_template("login.html")

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        flash("You have been logged out.", "info")
        return redirect(url_for("index"))

    @app.route("/p/<token>")
    def public_profile(token):
        u = User.query.filter_by(share_token=token, role="candidate", is_active=True).first_or_404()
        if not u.consent_share:
            return render_template("error.html", code=404,
                                   message="This profile is not being shared at the moment."), 404
        log("profile_view_link", u.id, f"viewer={'anonymous' if not g.user else g.user.email}")
        db.session.commit()
        return render_template("report.html", u=u, public=True)

    # ---- dashboard router

    @app.route("/dashboard")
    @login_required()
    def dashboard():
        r = g.user.role
        if r == "assessor":
            return redirect(url_for("review_queue"))
        if r == "employer":
            return redirect(url_for("talent"))
        if r == "admin":
            return redirect(url_for("admin"))
        u = g.user
        steps = [
            ("Complete your profile", bool(u.headline and u.bio), url_for("profile")),
            ("Add your skills", bool(u.skills), url_for("skill_new")),
            ("Upload evidence", bool(u.evidence), url_for("evidence_list")),
            ("Request an assessment", any(s.status != "self_declared" for s in u.skills), None),
            ("Share your competency report", u.consent_share, url_for("report")),
        ]
        appeals = Appeal.query.filter_by(user_id=u.id).order_by(Appeal.created_at.desc()).all()
        return render_template("dashboard.html", u=u, steps=steps, appeals=appeals)

    # ---- candidate: profile & experience

    @app.route("/profile", methods=["GET", "POST"])
    @login_required("candidate")
    def profile():
        u = g.user
        if request.method == "POST":
            f = request.form
            u.full_name = f.get("full_name", u.full_name).strip() or u.full_name
            u.headline = f.get("headline", "").strip()[:160]
            u.location = f.get("location", "").strip()[:120]
            u.bio = f.get("bio", "").strip()
            db.session.commit()
            flash("Profile saved.", "success")
            return redirect(url_for("profile"))
        return render_template("profile.html", u=u)

    @app.route("/experience", methods=["POST"])
    @login_required("candidate")
    def experience_add():
        f = request.form
        if not f.get("title", "").strip():
            flash("Job title is required.", "error")
        else:
            db.session.add(Experience(
                user_id=g.user.id, title=f["title"].strip(), organisation=f.get("organisation", "").strip(),
                country=f.get("country", "").strip(),
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
              else "Sharing turned off. Employers and your link can no longer see your profile.",
              "success")
        return redirect(request.referrer or url_for("report"))

    # ---- candidate: skills

    def skill_from_form(s, f):
        s.name = f.get("name", "").strip()[:120]
        s.category = f.get("category", "Other")[:80]
        s.claimed_level = to_int(f.get("claimed_level"), 3, 1, 5)
        s.years = to_int(f.get("years"), 0, 0, 60)
        s.description = f.get("description", "").strip()

    @app.route("/skills/new", methods=["GET", "POST"])
    @login_required("candidate")
    def skill_new():
        if request.method == "POST":
            s = Skill(user_id=g.user.id)
            skill_from_form(s, request.form)
            if not s.name:
                flash("Skill name is required.", "error")
                return render_template("skill_form.html", s=s)
            db.session.add(s)
            db.session.commit()
            flash(f"“{s.name}” added as a self-declared skill.", "success")
            return redirect(url_for("skill_detail", sid=s.id))
        return render_template("skill_form.html", s=None)

    def own_skill(sid):
        return Skill.query.filter_by(id=sid, user_id=g.user.id).first_or_404()

    @app.route("/skills/<int:sid>")
    @login_required("candidate")
    def skill_detail(sid):
        s = own_skill(sid)
        return render_template("skill_detail.html", s=s, task=task_for(s))

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
                return render_template("skill_form.html", s=s)
            db.session.commit()
            flash("Skill updated.", "success")
            return redirect(url_for("skill_detail", sid=sid))
        return render_template("skill_form.html", s=s)

    @app.route("/skills/<int:sid>/delete", methods=["POST"])
    @login_required("candidate")
    def skill_delete(sid):
        s = own_skill(sid)
        db.session.delete(s)
        db.session.commit()
        flash("Skill removed.", "info")
        return redirect(url_for("dashboard"))

    @app.route("/skills/<int:sid>/request", methods=["POST"])
    @login_required("candidate")
    def skill_request(sid):
        s = own_skill(sid)
        resp = request.form.get("task_response", "").strip()
        if s.status not in ("self_declared", "not_verified"):
            flash("This skill is already awaiting or has passed assessment.", "info")
        elif len(resp) < 50:
            flash("Please give a fuller answer to the practical task (at least 50 characters).", "error")
        else:
            s.task_response = resp
            s.status = "pending"
            s.requested_at = utcnow()
            log("assessment_requested", g.user.id, f"skill={s.id}")
            db.session.commit()
            flash("Assessment requested. An assessor will review your evidence and task.", "success")
        return redirect(url_for("skill_detail", sid=sid))

    # ---- candidate: evidence

    @app.route("/evidence", methods=["GET", "POST"])
    @login_required("candidate")
    def evidence_list():
        u = g.user
        if request.method == "POST":
            f = request.form
            file = request.files.get("file")
            link = f.get("link", "").strip()
            title = f.get("title", "").strip()
            if not title:
                flash("Please give the evidence a title.", "error")
                return redirect(url_for("evidence_list"))
            if link and not link.startswith(("http://", "https://")):
                flash("Links must start with http:// or https://", "error")
                return redirect(url_for("evidence_list"))
            if not (file and file.filename) and not link:
                flash("Upload a file or add a link.", "error")
                return redirect(url_for("evidence_list"))
            ev = Evidence(user_id=u.id, title=title[:160],
                          kind=f.get("kind") if f.get("kind") in EVIDENCE_KINDS else "other",
                          description=f.get("description", "").strip(), link=link[:500])
            sid = to_int(f.get("skill_id"), None)
            if sid and Skill.query.filter_by(id=sid, user_id=u.id).first():
                ev.skill_id = sid
            if file and file.filename:
                ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
                if ext not in ALLOWED_EXT:
                    flash("File type not allowed. Use PDF, image, Word, text or zip.", "error")
                    return redirect(url_for("evidence_list"))
                ev.stored_name = f"{uuid.uuid4().hex}.{ext}"
                ev.original_name = Path(file.filename).name[:255]
                file.save(Path(app.config["UPLOAD_FOLDER"]) / ev.stored_name)
            db.session.add(ev)
            db.session.commit()
            flash("Evidence saved securely.", "success")
            return redirect(request.form.get("back") or url_for("evidence_list"))
        return render_template("evidence.html", u=u, preselect=to_int(request.args.get("skill"), None))

    @app.route("/evidence/<int:eid>/delete", methods=["POST"])
    @login_required("candidate")
    def evidence_delete(eid):
        ev = Evidence.query.filter_by(id=eid, user_id=g.user.id).first_or_404()
        if ev.stored_name:
            (Path(app.config["UPLOAD_FOLDER"]) / ev.stored_name).unlink(missing_ok=True)
        db.session.delete(ev)
        db.session.commit()
        flash("Evidence deleted.", "info")
        return redirect(url_for("evidence_list"))

    @app.route("/evidence/<int:eid>/file")
    @login_required()
    def evidence_file(eid):
        ev = db.get_or_404(Evidence, eid)
        if not ev.stored_name or not can_view_evidence(g.user, ev):
            abort(403 if ev.stored_name else 404)
        if g.user.id != ev.user_id:
            log("evidence_viewed", ev.user_id, f"evidence={ev.id}")
            db.session.commit()
        return send_from_directory(app.config["UPLOAD_FOLDER"], ev.stored_name,
                                   as_attachment=True, download_name=ev.original_name)

    # ---- candidate: report, appeals, data rights

    @app.route("/report")
    @login_required("candidate")
    def report():
        return render_template("report.html", u=g.user, public=False)

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
            db.session.add(Appeal(assessment_id=a.id, user_id=g.user.id, reason=reason))
            log("appeal_submitted", g.user.id, f"assessment={a.id}")
            db.session.commit()
            flash("Appeal submitted. An administrator will review it and a different assessor "
                  "will reassess if it is upheld.", "success")
        return redirect(url_for("skill_detail", sid=a.skill_id))

    @app.route("/account", methods=["GET"])
    @login_required()
    def account():
        return render_template("account.html", u=g.user)

    @app.route("/account/password", methods=["POST"])
    @login_required()
    def account_password():
        f = request.form
        if not g.user.check_password(f.get("current", "")):
            flash("Current password is incorrect.", "error")
        elif len(f.get("new", "")) < 8 or f.get("new") != f.get("confirm"):
            flash("New password must be at least 8 characters and match the confirmation.", "error")
        else:
            g.user.set_password(f["new"])
            log("password_changed", g.user.id)
            db.session.commit()
            flash("Password changed.", "success")
        return redirect(url_for("account"))

    @app.route("/account/export")
    @login_required()
    def account_export():
        u = g.user
        data = {
            "account": {"name": u.full_name, "email": u.email, "role": u.role, "headline": u.headline,
                        "location": u.location, "bio": u.bio, "organisation": u.organisation,
                        "sharing_consent": u.consent_share,
                        "consent_at": u.consent_at.isoformat() if u.consent_at else None,
                        "created_at": u.created_at.isoformat()},
            "experience": [dict(title=e.title, organisation=e.organisation, country=e.country,
                                start_year=e.start_year, end_year=e.end_year,
                                description=e.description) for e in u.experiences],
            "skills": [dict(name=s.name, category=s.category, claimed_level=s.claimed_level,
                            years=s.years, status=s.status, description=s.description,
                            task_response=s.task_response,
                            assessments=[dict(reference=a.reference, outcome=a.outcome,
                                              assessed_level=a.assessed_level, total=a.total,
                                              comments=a.comments, assessor=a.assessor.full_name,
                                              date=a.created_at.isoformat()) for a in s.assessments])
                       for s in u.skills],
            "evidence": [dict(title=e.title, kind=e.kind, link=e.link, file=e.original_name,
                              uploaded_at=e.uploaded_at.isoformat()) for e in u.evidence],
            "access_log": [dict(action=l.action, detail=l.detail, at=l.created_at.isoformat())
                           for l in AuditLog.query.filter_by(subject_user_id=u.id)
                           .order_by(AuditLog.created_at.desc()).all()],
        }
        log("data_exported", u.id)
        db.session.commit()
        return Response(json.dumps(data, indent=2), mimetype="application/json",
                        headers={"Content-Disposition": "attachment; filename=skillproof-my-data.json"})

    @app.route("/account/delete", methods=["POST"])
    @login_required()
    def account_delete():
        u = g.user
        if not u.check_password(request.form.get("password", "")):
            flash("Password incorrect. Your account was not deleted.", "error")
            return redirect(url_for("account"))
        if u.role == "admin" and User.query.filter_by(role="admin", is_active=True).count() <= 1:
            flash("You are the only administrator and cannot delete this account.", "error")
            return redirect(url_for("account"))
        for ev in u.evidence:
            if ev.stored_name:
                (Path(app.config["UPLOAD_FOLDER"]) / ev.stored_name).unlink(missing_ok=True)
        Appeal.query.filter_by(user_id=u.id).delete()
        log("account_deleted", None, f"user_id={u.id}")
        if u.role == "candidate":
            db.session.delete(u)
        else:
            # assessors/admins keep an anonymised record so past decisions stay accountable
            u.full_name, u.email, u.is_active = "Former reviewer", f"deleted-{u.id}@skillproof.invalid", False
            u.set_password(secrets.token_hex(16))
        db.session.commit()
        session.clear()
        flash("Your account and personal data have been deleted.", "info")
        return redirect(url_for("index"))

    # ---- assessor

    @app.route("/review")
    @login_required("assessor", "admin")
    def review_queue():
        pending = (Skill.query.filter(Skill.status == "pending", Skill.user_id != g.user.id)
                   .order_by(Skill.requested_at).all())
        mine = (Assessment.query.filter_by(assessor_id=g.user.id)
                .order_by(Assessment.created_at.desc()).limit(20).all())
        return render_template("review_queue.html", pending=pending, mine=mine)

    @app.route("/review/<int:sid>", methods=["GET", "POST"])
    @login_required("assessor", "admin")
    def review(sid):
        s = db.get_or_404(Skill, sid)
        if s.user_id == g.user.id:
            abort(403)
        # Assessors only see candidates who asked to be assessed (or whom they assessed).
        if (g.user.role != "admin" and s.status != "pending"
                and not any(a.assessor_id == g.user.id for a in s.assessments)):
            abort(403)
        prior_assessors = {a.assessor_id for a in s.assessments if any(ap.status == "upheld" for ap in a.appeals)}
        if g.user.id in prior_assessors:
            flash("This skill is being reassessed after an appeal against your decision, "
                  "so another assessor must review it.", "info")
            return redirect(url_for("review_queue"))
        if request.method == "POST":
            if s.status != "pending":
                flash("This skill is no longer awaiting assessment.", "info")
                return redirect(url_for("review_queue"))
            f = request.form
            scores = {k: to_int(f.get(f"score_{k}"), -1) for k in CRITERIA}
            comments = f.get("comments", "").strip()
            if any(v < 0 or v > 5 for v in scores.values()):
                flash("Score every criterion from 0 to 5.", "error")
            elif len(comments) < 30:
                flash("Write feedback for the candidate (at least 30 characters). "
                      "Clear reasons are required for every decision.", "error")
            else:
                total = sum(scores.values())
                passed = total >= PASS_MARK and min(scores.values()) >= 2
                a = Assessment(skill_id=s.id, assessor_id=g.user.id,
                               score_knowledge=scores["knowledge"], score_practical=scores["practical"],
                               score_evidence=scores["evidence"], score_communication=scores["communication"],
                               assessed_level=to_int(f.get("assessed_level"), 3, 1, 5) if passed else None,
                               outcome="verified" if passed else "not_verified", comments=comments)
                s.status = a.outcome
                db.session.add(a)
                log("assessment_completed", s.user_id, f"skill={s.id} outcome={a.outcome} total={total}")
                db.session.commit()
                flash(f"Assessment saved: {'verified' if passed else 'not verified'} ({total}/20).", "success")
                return redirect(url_for("review_queue"))
        log("evidence_reviewed", s.user_id, f"skill={s.id}")
        db.session.commit()
        return render_template("review.html", s=s, task=task_for(s))

    # ---- employer

    @app.route("/talent")
    @login_required("employer", "admin")
    def talent():
        q = request.args.get("q", "").strip()
        cat = request.args.get("category", "")
        verified_only = (request.args.get("verified") == "1") if "searched" in request.args else True
        query = (db.session.query(User).join(Skill, Skill.user_id == User.id)
                 .filter(User.role == "candidate", User.consent_share.is_(True), User.is_active.is_(True)))
        if verified_only:
            query = query.filter(Skill.status == "verified")
        if q:
            like = f"%{q}%"
            query = query.filter(or_(Skill.name.ilike(like), User.headline.ilike(like)))
        if cat:
            query = query.filter(Skill.category == cat)
        people = query.distinct().order_by(User.full_name).all()
        return render_template("talent.html", people=people, q=q, cat=cat, verified_only=verified_only)

    @app.route("/talent/<int:uid>")
    @login_required("employer", "admin")
    def talent_profile(uid):
        u = User.query.filter_by(id=uid, role="candidate", consent_share=True, is_active=True).first_or_404()
        log("profile_view_employer", u.id, f"employer={g.user.organisation or g.user.email}")
        db.session.commit()
        return render_template("report.html", u=u, public=True)

    # ---- admin

    @app.route("/admin")
    @login_required("admin")
    def admin():
        metrics = [
            ("Registered users", User.query.filter_by(is_active=True).count()),
            ("Candidates", User.query.filter_by(role="candidate").count()),
            ("Completed skills profiles", db.session.query(func.count(func.distinct(Skill.user_id))).scalar()),
            ("Evidence records", Evidence.query.count()),
            ("Assessments completed", Assessment.query.count()),
            ("Verified skills", Skill.query.filter_by(status="verified").count()),
            ("Awaiting assessment", Skill.query.filter_by(status="pending").count()),
            ("Shared competency reports", User.query.filter_by(role="candidate", consent_share=True).count()),
            ("Employers", User.query.filter_by(role="employer").count()),
            ("Employer profile views", AuditLog.query.filter_by(action="profile_view_employer").count()),
            ("Open appeals", Appeal.query.filter_by(status="open").count()),
        ]
        users = User.query.filter_by(is_active=True).order_by(User.created_at.desc()).all()
        return render_template("admin.html", metrics=metrics, users=users, roles=ROLES)

    @app.route("/admin/users/<int:uid>/role", methods=["POST"])
    @login_required("admin")
    def admin_role(uid):
        u = db.get_or_404(User, uid)
        role = request.form.get("role")
        if role not in ROLES:
            abort(400)
        if u.id == g.user.id:
            flash("You can't change your own role.", "error")
        else:
            old, u.role = u.role, role
            log("role_changed", u.id, f"{old} -> {role}")
            db.session.commit()
            flash(f"{u.full_name} is now {role}.", "success")
        return redirect(url_for("admin"))

    @app.route("/admin/appeals")
    @login_required("admin")
    def admin_appeals():
        appeals = Appeal.query.order_by(Appeal.status != "open", Appeal.created_at.desc()).all()
        return render_template("admin_appeals.html", appeals=appeals)

    @app.route("/admin/appeals/<int:apid>", methods=["POST"])
    @login_required("admin")
    def admin_appeal_resolve(apid):
        ap = db.get_or_404(Appeal, apid)
        decision = request.form.get("decision")
        note = request.form.get("resolution", "").strip()
        if ap.status != "open" or decision not in ("upheld", "rejected") or len(note) < 10:
            flash("Choose a decision and explain it (at least 10 characters).", "error")
            return redirect(url_for("admin_appeals"))
        ap.status, ap.resolution, ap.resolver_id, ap.resolved_at = decision, note, g.user.id, utcnow()
        if decision == "upheld":
            ap.assessment.skill.status = "pending"
            ap.assessment.skill.requested_at = utcnow()
        log("appeal_" + decision, ap.user_id, f"appeal={ap.id}")
        db.session.commit()
        flash("Appeal upheld: the skill is back in the queue for a different assessor."
              if decision == "upheld" else "Appeal rejected. The candidate can see your reasons.", "success")
        return redirect(url_for("admin_appeals"))

    @app.route("/admin/audit")
    @login_required("admin")
    def admin_audit():
        entries = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(300).all()
        return render_template("admin_audit.html", entries=entries)

    @app.route("/my-access-log")
    @login_required("candidate")
    def my_access_log():
        entries = (AuditLog.query.filter(AuditLog.subject_user_id == g.user.id)
                   .order_by(AuditLog.created_at.desc()).limit(200).all())
        return render_template("admin_audit.html", entries=entries, mine=True)


app = create_app()

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", port=int(os.environ.get("PORT", 5050)))
