"""Shared helpers: access control, audit, notifications, tokens, email, settings, stats."""
import os
import smtplib
from collections import OrderedDict
from datetime import timedelta
from email.message import EmailMessage
from functools import wraps

from flask import abort, current_app, flash, g, redirect, request, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from markupsafe import Markup
from sqlalchemy import func

from i18n import gettext
from models import AuditLog, Notification, Setting, db, utcnow

PRACTICAL_TASKS = {
    "Software development": "Share a link to code you wrote (GitHub, GitLab or a zip upload) and explain in 150-300 words: what problem it solves, one design decision you made and why, and how you tested it.",
    "IT support & networking": "Describe step by step how you would diagnose an office where 10 computers suddenly cannot reach the internet but the router shows as online. Include the tools and commands you would use.",
    "Healthcare": "Describe a real case you handled (no patient names): the situation, the actions you took, the protocols you followed and the outcome.",
    "Teaching & training": "Outline a 45-minute lesson plan on a topic you teach: learning objectives, activities, and how you check learners understood.",
    "Trades & vocational": "Upload photos or a short video of work you completed and describe the materials, tools, safety steps and time it took.",
    "Business & finance": "Describe a budget, report or process you were responsible for, the figures or scale involved, and a problem you solved.",
}
DEFAULT_TASK = "Describe a piece of work that demonstrates this skill: what you did, the tools or methods you used, the result, and how someone could check it. Add links where possible."
CATEGORIES = list(PRACTICAL_TASKS) + ["Other"]

ALLOWED_EXT = {"pdf", "png", "jpg", "jpeg", "doc", "docx", "txt", "zip"}
MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15

DEFAULT_SETTINGS = {
    "registration_open": "1",
    "employer_approval": "1",   # employers need admin approval
    "assessor_applications": "1",  # people can apply to become assessors
    "candidate_approval": "0",  # candidates are active straight away
    "require_email_verification": "0",  # block key actions until email verified
    "assessment_sla_days": "7",
    "announcement": "",
}


def task_for(skill):
    return PRACTICAL_TASKS.get(skill.category, DEFAULT_TASK)


# ---------------------------------------------------------------- settings

def get_setting(key):
    cache = g.setdefault("_settings", {})
    if key not in cache:
        row = db.session.get(Setting, key)
        cache[key] = row.value if row else DEFAULT_SETTINGS.get(key, "")
    return cache[key]


def setting_on(key):
    return get_setting(key) == "1"


def set_setting(key, value):
    row = db.session.get(Setting, key) or Setting(key=key)
    row.value = value
    db.session.add(row)
    g.setdefault("_settings", {})[key] = value


# ---------------------------------------------------------------- audit & notify

def client_ip():
    return (request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip())[:64]


def log(action, subject_user_id=None, detail="", actor=None):
    actor = actor if actor is not None else g.get("user")
    db.session.add(AuditLog(actor_id=actor.id if actor else None, action=action,
                            subject_user_id=subject_user_id, detail=(detail or "")[:500], ip=client_ip()))


def notify(user_id, message, link="", kind="info"):
    db.session.add(Notification(user_id=user_id, message=message[:300], link=link, kind=kind))


# ---------------------------------------------------------------- access control

def login_required(*roles):
    """Require login; optionally restrict to roles. Pending accounts are routed by before_request."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if not g.user:
                flash(gettext("Please log in to continue."), "info")
                return redirect(url_for("login", next=request.full_path.rstrip("?")))
            if roles and g.user.role not in roles:
                abort(403)
            return fn(*a, **kw)
        return wrapper
    return deco


def email_verified_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if setting_on("require_email_verification") and not g.user.email_verified:
            flash("Please verify your email address first. Check your inbox or resend the link.", "error")
            return redirect(request.referrer or url_for("dashboard"))
        return fn(*a, **kw)
    return wrapper


def can_view_evidence(user, ev):
    """Evidence is private: owner, assessors and admins only. Never employers."""
    return user and (user.id == ev.user_id or user.role in ("assessor", "admin"))


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


def safe_next(target, fallback):
    return target if target and target.startswith("/") and not target.startswith("//") else fallback


def password_problems(pw, email="", name=""):
    issues = []
    if len(pw) < 8:
        issues.append("at least 8 characters")
    if not any(c.isalpha() for c in pw) or not any(c.isdigit() for c in pw):
        issues.append("letters and numbers")
    low = pw.lower()
    if email and email.split("@")[0].lower() in low and len(email.split("@")[0]) > 3:
        issues.append("not containing your email")
    if low in {"password1", "12345678a", "qwerty123", "skillproof1"}:
        issues.append("not a common password")
    return issues


# ---------------------------------------------------------------- tokens & email

def _serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])


def make_token(purpose, user):
    # Include part of the password hash for reset tokens so they become invalid once used.
    payload = {"uid": user.id, "p": purpose}
    if purpose == "reset":
        payload["h"] = user.password_hash[-12:]
    return _serializer().dumps(payload, salt=f"sp-{purpose}")


def read_token(purpose, token, max_age):
    from models import User
    try:
        data = _serializer().loads(token, salt=f"sp-{purpose}", max_age=max_age)
    except (SignatureExpired, BadSignature):
        return None
    user = db.session.get(User, data.get("uid"))
    if not user or data.get("p") != purpose:
        return None
    if purpose == "reset" and data.get("h") != user.password_hash[-12:]:
        return None
    return user


def send_email(to, subject, body, dev_link=None):
    """Send via SMTP if configured; otherwise print to the console and, in dev, show the link."""
    host = os.environ.get("SMTP_HOST")
    if host:
        msg = EmailMessage()
        msg["From"] = os.environ.get("MAIL_FROM", "SkillProof <no-reply@skillproof.local>")
        msg["To"], msg["Subject"] = to, subject
        msg.set_content(body)
        try:
            with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", 587)), timeout=10) as s:
                if os.environ.get("SMTP_TLS", "1") == "1":
                    s.starttls()
                if os.environ.get("SMTP_USER"):
                    s.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
                s.send_message(msg)
            return True
        except Exception as e:  # noqa: BLE001 - never break the user flow on mail errors
            current_app.logger.error("Email to %s failed: %s", to, e)
            return False
    current_app.logger.warning("[DEV EMAIL] To: %s | %s\n%s", to, subject, body)
    if dev_link and current_app.config.get("SHOW_DEV_LINKS"):
        flash(Markup('{} <a href="{}">{}</a>').format(gettext("Development mode (no email server configured):"),
                                                       dev_link, gettext("open the link from the email")), "dev")
    return False


def send_verification(user):
    link = url_for("verify_email", token=make_token("verify", user), _external=True)
    send_email(user.email, "Confirm your SkillProof email",
               f"Hello {user.first_name},\n\nConfirm your email address for SkillProof:\n{link}\n\n"
               "This link expires in 3 days. If you did not create an account, ignore this email.",
               dev_link=link)


def send_reset(user):
    link = url_for("reset_password", token=make_token("reset", user), _external=True)
    send_email(user.email, "Reset your SkillProof password",
               f"Hello {user.first_name},\n\nReset your password here (valid for 1 hour):\n{link}\n\n"
               "If you did not ask for this, you can ignore this email. Your password has not changed.",
               dev_link=link)


# ---------------------------------------------------------------- stats helpers

def daily_counts(column, days=30, filters=()):
    """Return (labels, values) of row counts per day for the last `days` days."""
    start = (utcnow() - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    day = func.date(column)
    q = db.session.query(day, func.count()).filter(column >= start, *filters).group_by(day)
    found = {str(d): n for d, n in q.all()}
    series = OrderedDict()
    for i in range(days):
        d = (start + timedelta(days=i)).date()
        series[d] = found.get(str(d), 0)
    return [d.strftime("%d %b") for d in series], list(series.values())


def cumulative(model, column, days=30):
    """Running total of rows per day over the last `days` days (for growth charts)."""
    labels, daily = daily_counts(column, days)
    start = (utcnow() - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    total = model.query.filter(column < start).count()
    out = []
    for n in daily:
        total += n
        out.append(total)
    return labels, out


def count_between(model, column, start, end, *filters):
    return model.query.filter(column >= start, column < end, *filters).count()


def trend(model, column, *filters, days=7):
    """Count in the last `days` and % change against the previous period."""
    now = utcnow()
    cur = count_between(model, column, now - timedelta(days=days), now + timedelta(seconds=1), *filters)
    prev = count_between(model, column, now - timedelta(days=2 * days), now - timedelta(days=days), *filters)
    pct = None if prev == 0 else round((cur - prev) / prev * 100)
    return cur, pct


def paginate(query, per_page=15):
    page = to_int(request.args.get("page"), 1, 1)
    return query.paginate(page=page, per_page=per_page, error_out=False)
