"""Public pages, shared account pages, notifications."""
import json
import secrets
from pathlib import Path

from flask import Response, current_app, flash, g, redirect, render_template, request, session, url_for
from sqlalchemy import or_

from core import log, login_required, password_problems, safe_next
from models import Appeal, Application, AuditLog, DocImport, Job, Notification, Shortlist, Skill, User, db


def register(app):

    @app.route("/")
    def index():
        stats = dict(
            candidates=User.query.filter_by(role="candidate").count(),
            verified=Skill.query.filter_by(status="verified").count(),
            employers=User.query.filter_by(role="employer", status="active").count(),
        )
        return render_template("index.html", stats=stats)

    @app.route("/privacy")
    def privacy():
        return render_template("privacy.html")

    @app.route("/p/<token>")
    def public_profile(token):
        u = User.query.filter_by(share_token=token, role="candidate", status="active").first_or_404()
        if not u.consent_share:
            return render_template("error.html", code=404,
                                   message="This profile is not being shared at the moment."), 404
        if not g.user or g.user.id != u.id:
            log("profile_view_link", u.id, "viewer=" + ("anonymous" if not g.user else g.user.email))
            db.session.commit()
        return render_template("candidate/report_public.html", u=u)

    # ---- notifications

    @app.route("/notifications")
    @login_required()
    def notifications():
        items = g.user.notifications.limit(100).all()
        return render_template("notifications.html", items=items)

    @app.route("/notifications/read", methods=["POST"])
    @login_required()
    def notifications_read():
        Notification.query.filter_by(user_id=g.user.id, read=False).update({"read": True})
        db.session.commit()
        return redirect(safe_next(request.form.get("next"), url_for("notifications")))

    @app.route("/n/<int:nid>")
    @login_required()
    def notification_open(nid):
        n = Notification.query.filter_by(id=nid, user_id=g.user.id).first_or_404()
        n.read = True
        db.session.commit()
        # Never send people back to the list they clicked from: fall back to their home page.
        return redirect(n.link if n.link.startswith("/") and not n.link.startswith("//") else url_for("dashboard"))

    # ---- account (all roles)

    @app.route("/account")
    @login_required()
    def account():
        logins = (AuditLog.query.filter(AuditLog.subject_user_id == g.user.id,
                                        AuditLog.action.in_(["login", "login_failed", "account_locked",
                                                             "password_changed", "password_reset"]))
                  .order_by(AuditLog.created_at.desc()).limit(8).all())
        return render_template("account.html", u=g.user, logins=logins)

    @app.route("/account/profile", methods=["POST"])
    @login_required()
    def account_profile():
        u, f = g.user, request.form
        name = " ".join(f.get("full_name", "").split())
        if len(name) >= 2:
            u.full_name = name[:120]
        u.phone = f.get("phone", "").strip()[:40]
        if u.role in ("employer", "assessor", "admin"):
            u.organisation = f.get("organisation", "").strip()[:160]
            u.website = f.get("website", "").strip()[:255]
        if u.role == "assessor":
            u.expertise = f.get("expertise", "").strip()[:255]
        db.session.commit()
        flash("Account details saved.", "success")
        return redirect(url_for("account"))

    @app.route("/account/password", methods=["POST"])
    @login_required()
    def account_password():
        f = request.form
        problems = password_problems(f.get("new", ""), g.user.email, g.user.full_name)
        if not g.user.check_password(f.get("current", "")):
            flash("Current password is incorrect.", "error")
        elif problems:
            flash("New password needs " + ", ".join(problems) + ".", "error")
        elif f.get("new") != f.get("confirm"):
            flash("New passwords do not match.", "error")
        else:
            g.user.set_password(f["new"])
            log("password_changed", g.user.id)
            db.session.commit()
            session["sv"] = g.user.session_version  # keep this session, end all others
            flash("Password changed. You've been signed out on your other devices.", "success")
        return redirect(url_for("account"))

    @app.route("/account/export")
    @login_required()
    def account_export():
        u = g.user
        data = {
            "account": {"name": u.full_name, "email": u.email, "role": u.role, "status": u.status,
                        "headline": u.headline, "location": u.location, "phone": u.phone, "bio": u.bio,
                        "organisation": u.organisation, "email_verified": u.email_verified,
                        "identity_verified": u.identity_verified, "sharing_consent": u.consent_share,
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
            "access_log": [dict(action=a.action, detail=a.detail, at=a.created_at.isoformat())
                           for a in AuditLog.query.filter_by(subject_user_id=u.id)
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
        if u.role == "admin" and User.query.filter_by(role="admin", status="active").count() <= 1:
            flash("You are the only administrator and cannot delete this account.", "error")
            return redirect(url_for("account"))
        for ev in u.evidence:
            if ev.stored_name:
                (Path(current_app.config["UPLOAD_FOLDER"]) / ev.stored_name).unlink(missing_ok=True)
        Appeal.query.filter_by(user_id=u.id).delete()
        Notification.query.filter_by(user_id=u.id).delete()
        for imp in DocImport.query.filter_by(user_id=u.id):
            if imp.status == "ready":
                (Path(current_app.config["UPLOAD_FOLDER"]) / imp.stored_name).unlink(missing_ok=True)
            db.session.delete(imp)
        Application.query.filter_by(candidate_id=u.id).delete()
        for job in Job.query.filter_by(employer_id=u.id):
            db.session.delete(job)
        Shortlist.query.filter(or_(Shortlist.employer_id == u.id, Shortlist.candidate_id == u.id)).delete()
        log("account_deleted", None, f"user_id={u.id} role={u.role}", actor=None)
        if u.role in ("candidate", "employer"):
            db.session.delete(u)
        else:
            # assessors/admins keep an anonymised record so past decisions stay accountable
            u.full_name, u.email = "Former reviewer", f"deleted-{u.id}@skillproof.invalid"
            u.status, u.phone, u.bio = "suspended", "", ""
            u.set_password(secrets.token_hex(16))
        db.session.commit()
        session.clear()
        flash("Your account and personal data have been deleted.", "info")
        return redirect(url_for("index"))
