"""Registration, login, email verification, password reset, pending approval."""
from datetime import timedelta

from flask import flash, g, redirect, render_template, request, session, url_for

from core import (
    LOCKOUT_MINUTES,
    MAX_FAILED_LOGINS,
    log,
    notify,
    password_problems,
    read_token,
    safe_next,
    send_reset,
    send_verification,
    setting_on,
)
from i18n import gettext as _
from models import User, db, utcnow


def start_session(user, remember=False):
    session.clear()
    session.permanent = bool(remember)
    session["uid"] = user.id
    session["sv"] = user.session_version


def register(app):

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if g.user:
            return redirect(url_for("dashboard"))
        if not setting_on("registration_open"):
            return render_template("auth/closed.html")
        roles = ["candidate", "employer"] + (["assessor"] if setting_on("assessor_applications") else [])
        if request.method == "POST":
            f = request.form
            email = f.get("email", "").strip().lower()
            name = " ".join(f.get("full_name", "").split())
            pw = f.get("password", "")
            role = f.get("role") if f.get("role") in roles else "candidate"
            errors = []
            if len(name) < 2:
                errors.append(_("Please enter your full name."))
            if "@" not in email or "." not in email.split("@")[-1] or len(email) > 255:
                errors.append(_("Please enter a valid email address."))
            problems = password_problems(pw, email, name)
            if problems:
                errors.append(_("Password needs: {items}.", items=", ".join(_(x) for x in problems)))
            if pw != f.get("confirm"):
                errors.append(_("Passwords do not match."))
            if role in ("employer", "assessor") and not f.get("organisation", "").strip():
                errors.append(_("Please enter your organisation."))
            if not f.get("agree"):
                errors.append(_("You need to accept the privacy notice to create an account."))
            if User.query.filter_by(email=email).first():
                errors.append(_("An account with this email already exists. Try logging in or resetting your password."))
            if errors:
                for e in errors:
                    flash(e, "error")
                return render_template("auth/register.html", form=f, roles=roles)

            needs_approval = {"candidate": setting_on("candidate_approval"),
                              "employer": setting_on("employer_approval"), "assessor": True}[role]
            u = User(full_name=name, email=email, role=role,
                     status="pending" if needs_approval else "active",
                     organisation=f.get("organisation", "").strip()[:160],
                     website=f.get("website", "").strip()[:255],
                     expertise=f.get("expertise", "").strip()[:255],
                     location=f.get("location", "").strip()[:120])
            u.set_password(pw)
            db.session.add(u)
            db.session.flush()
            log("register", u.id, f"role={role} status={u.status}", actor=u)
            if needs_approval:
                for admin in User.query.filter_by(role="admin", status="active"):
                    notify(admin.id, f"New {role} account awaiting approval: {u.full_name}",
                           url_for("admin_user", uid=u.id), "warning")
            notify(u.id, "Welcome to SkillProof! Confirm your email to secure your account.",
                   url_for("account"), "info")
            db.session.commit()
            start_session(u)
            send_verification(u)
            if needs_approval:
                return redirect(url_for("pending"))
            flash(_("Welcome to SkillProof! We've sent a confirmation link to your email."), "success")
            return redirect(url_for("dashboard"))
        return render_template("auth/register.html", form={"role": request.args.get("role", "candidate")}, roles=roles)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if g.user:
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            u = User.query.filter_by(email=email).first()
            now = utcnow()
            if u and u.locked_until and u.locked_until > now:
                mins = int((u.locked_until - now).total_seconds() // 60) + 1
                flash(f"Too many failed attempts. For your security this account is locked for {mins} more minute(s), "
                      "or you can reset your password.", "error")
                return render_template("auth/login.html", email=email)
            if not u or not u.check_password(request.form.get("password", "")):
                if u:
                    u.failed_logins += 1
                    if u.failed_logins >= MAX_FAILED_LOGINS:
                        u.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
                        u.failed_logins = 0
                        log("account_locked", u.id, "too many failed logins", actor=u)
                        notify(u.id, "Your account was temporarily locked after several failed login attempts. "
                                     "If this wasn't you, reset your password.", url_for("account"), "warning")
                    else:
                        log("login_failed", u.id, actor=u)
                    db.session.commit()
                flash(_("Incorrect email or password."), "error")
                return render_template("auth/login.html", email=email)
            if u.status in ("rejected", "suspended"):
                flash(f"This account is {u.status}. "
                      + (f"Reason: {u.status_reason}. " if u.status_reason else "")
                      + "Contact the SkillProof team if you think this is a mistake.", "error")
                return render_template("auth/login.html", email=email)
            u.failed_logins, u.locked_until, u.last_login_at = 0, None, now
            log("login", u.id, actor=u)
            db.session.commit()
            start_session(u, request.form.get("remember") == "1")
            if u.status == "pending":
                return redirect(url_for("pending"))
            flash(_("Welcome back, {name}.", name=u.first_name), "success")
            return redirect(safe_next(request.args.get("next"), url_for("dashboard")))
        return render_template("auth/login.html", email="")

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        flash(_("You have been logged out."), "info")
        return redirect(url_for("login"))

    @app.route("/pending")
    def pending():
        if not g.user:
            return redirect(url_for("login"))
        if g.user.status != "pending":
            return redirect(url_for("dashboard"))
        return render_template("auth/pending.html", u=g.user)

    @app.route("/verify/<token>")
    def verify_email(token):
        u = read_token("verify", token, max_age=3 * 86400)
        if not u:
            flash("That confirmation link is invalid or has expired. Log in and request a new one.", "error")
            return redirect(url_for("login"))
        if not u.email_verified:
            u.email_verified, u.email_verified_at = True, utcnow()
            log("email_verified", u.id, actor=u)
            db.session.commit()
        flash(_("Email confirmed. Thank you!"), "success")
        return redirect(url_for("dashboard") if g.user else url_for("login"))

    @app.route("/verify/resend", methods=["POST"])
    def resend_verification():
        if g.user and not g.user.email_verified:
            send_verification(g.user)
            flash("We've sent a new confirmation link to " + g.user.email + ".", "info")
        return redirect(request.referrer or url_for("dashboard"))

    @app.route("/forgot", methods=["GET", "POST"])
    def forgot_password():
        if request.method == "POST":
            u = User.query.filter_by(email=request.form.get("email", "").strip().lower()).first()
            if u and u.status in ("active", "pending"):
                send_reset(u)
                log("password_reset_requested", u.id, actor=u)
                db.session.commit()
            # Same message either way, so the form can't be used to discover accounts.
            flash(_("If an account exists for that email, we've sent a password reset link. It is valid for 1 hour."), "info")
            return redirect(url_for("login"))
        return render_template("auth/forgot.html")

    @app.route("/reset/<token>", methods=["GET", "POST"])
    def reset_password(token):
        u = read_token("reset", token, max_age=3600)
        if not u:
            flash("That reset link is invalid, expired or already used. Request a new one.", "error")
            return redirect(url_for("forgot_password"))
        if request.method == "POST":
            pw = request.form.get("password", "")
            problems = password_problems(pw, u.email, u.full_name)
            if problems:
                flash("Password needs " + ", ".join(problems) + ".", "error")
            elif pw != request.form.get("confirm"):
                flash("Passwords do not match.", "error")
            else:
                u.set_password(pw)
                u.failed_logins, u.locked_until = 0, None
                u.email_verified = True  # they proved access to the inbox
                log("password_reset", u.id, actor=u)
                notify(u.id, "Your password was changed. If this wasn't you, contact SkillProof immediately.",
                       url_for("account"), "warning")
                db.session.commit()
                flash(_("Password updated. You can now log in."), "success")
                return redirect(url_for("login"))
        return render_template("auth/reset.html", token=token)
