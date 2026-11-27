"""SkillProof: digital skills recognition and validation platform (prototype).

Application factory. Routes live in views/ (one module per area), helpers in core.py.
"""
import os
import secrets
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for

import ai
import core
import i18n
from models import ACCOUNT_STATUSES, CRITERIA, EVIDENCE_KINDS, LEVELS, PASS_MARK, SKILL_STATUSES, Job, User, db, utcnow

load_dotenv()
BASE_DIR = Path(__file__).resolve().parent

# Pages a logged-in but not-yet-approved account may still use.
PENDING_ALLOWED = {"pending", "logout", "account", "account_password", "account_profile", "account_export",
                   "account_delete", "verify_email", "resend_verification", "index", "privacy",
                   "notifications", "notifications_read", "static", "public_profile", "assistant_chat", "translate_content"}


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
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
        # Without an SMTP server, show verification/reset links on screen so the demo works.
        SHOW_DEV_LINKS=not os.environ.get("SMTP_HOST") and os.environ.get("SHOW_DEV_LINKS", "1") == "1",
    )
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
    db.init_app(app)
    with app.app_context():
        db.create_all()

    i18n.init_app(app)
    register_hooks(app)
    from views import admin, assessor, assistant, auth, candidate, employer, jobs, public, smart, translate
    for module in (public, auth, candidate, assessor, employer, admin, assistant, smart, jobs, translate):
        module.register(app)
    return app


def register_hooks(app):

    @app.before_request
    def load_user_and_csrf():
        g.user = None
        uid = session.get("uid")
        if uid:
            u = db.session.get(User, uid)
            # Session is invalid if the account is gone, blocked, or its password changed.
            if u and u.status in ("active", "pending") and session.get("sv") == u.session_version:
                g.user = u
            else:
                session.clear()
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(32)
        sent = request.form.get("csrf") or request.headers.get("X-CSRF-Token")
        if request.method == "POST" and sent != session["csrf"]:
            abort(400, "Invalid form token. Please reload the page and try again.")
        if g.user and g.user.status == "pending" and request.endpoint not in PENDING_ALLOWED:
            return redirect(url_for("pending"))

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        if g.get("user"):
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    @app.context_processor
    def inject():
        u = g.get("user")
        return dict(current_user=u, csrf_token=session.get("csrf"), now=utcnow(),
                    LEVELS=LEVELS, SKILL_STATUSES=SKILL_STATUSES, CRITERIA=CRITERIA,
                    EVIDENCE_KINDS=EVIDENCE_KINDS, PASS_MARK=PASS_MARK, CATEGORIES=core.CATEGORIES,
                    ACCOUNT_STATUSES=ACCOUNT_STATUSES, setting=core.get_setting,
                    unread=u.unread_count if u else 0,
                    TR_AVAILABLE=ai.configured(),
                    side_counts=({"pending": User.query.filter_by(status="pending").count()
                                             + User.query.filter_by(job_access="requested").count(),
                                  "jobs": Job.query.filter_by(status="pending").count()}
                                 if u and u.role == "admin" else {}),
                    recent_notes=u.notifications.limit(6).all() if u else [])

    @app.template_filter("ago")
    def ago(dt):
        if not dt:
            return "never"
        s = (utcnow() - dt).total_seconds()
        for limit, div, unit in ((60, 1, "second"), (3600, 60, "minute"), (86400, 3600, "hour"),
                                 (86400 * 30, 86400, "day"), (86400 * 365, 86400 * 30, "month")):
            if s < limit:
                n = max(1, int(s // div))
                return "just now" if unit == "second" else f"{n} {unit}{'s' if n != 1 else ''} ago"
        n = int(s // (86400 * 365))
        return f"{n} year{'s' if n != 1 else ''} ago"

    @app.template_filter("date")
    def fmt_date(dt, fmt="%d %b %Y"):
        return dt.strftime(fmt) if dt else ""

    def error(code, message):
        return render_template("error.html", code=code, message=message), code

    app.register_error_handler(400, lambda e: error(400, getattr(e, "description", "Bad request.")))
    app.register_error_handler(403, lambda e: error(403, "You do not have access to this page."))
    app.register_error_handler(404, lambda e: error(404, "We couldn't find that page."))

    @app.errorhandler(413)
    def too_large(e):
        flash("That file is too large. The limit is 10 MB.", "error")
        return redirect(request.referrer or url_for("dashboard"))


app = create_app()

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", port=int(os.environ.get("PORT", 5050)))
