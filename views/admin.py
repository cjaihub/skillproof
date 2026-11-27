"""Admin console: platform dashboard, user management & verification, appeals, audit, settings."""
import csv
import io

from flask import Response, abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import func, or_

from core import (
    CATEGORIES,
    DEFAULT_SETTINGS,
    cumulative,
    get_setting,
    log,
    login_required,
    notify,
    paginate,
    safe_next,
    set_setting,
    to_int,
    trend,
)
from models import ACCOUNT_STATUSES, ROLES, Appeal, Assessment, AuditLog, Evidence, Skill, User, db, utcnow

USER_ACTIONS = {
    "approve": "approved", "reject": "rejected", "suspend": "suspended", "reactivate": "reactivated",
    "verify_identity": "identity verified", "unverify_identity": "identity verification removed",
    "verify_email": "email marked verified", "unlock": "unlocked", "force_logout": "signed out everywhere",
}


def apply_user_action(u, action, reason=""):
    """Apply one admin action to a user. Returns an error message or None."""
    me = g.user
    if u.id == me.id and action in ("reject", "suspend", "force_logout"):
        return "You can't do that to your own account."
    if action == "approve":
        if u.status != "pending":
            return f"{u.full_name} is not pending approval."
        u.status, u.status_reason = "active", ""
        notify(u.id, "Your SkillProof account has been approved. Welcome aboard!", url_for("dashboard"), "success")
    elif action == "reject":
        if not reason:
            return "Give a reason when rejecting an account."
        u.status, u.status_reason = "rejected", reason
    elif action == "suspend":
        if not reason:
            return "Give a reason when suspending an account."
        u.status, u.status_reason = "suspended", reason
        u.session_version += 1
    elif action == "reactivate":
        u.status, u.status_reason = "active", ""
        notify(u.id, "Your SkillProof account has been reactivated.", url_for("dashboard"), "success")
    elif action == "verify_identity":
        u.identity_verified, u.verified_by_id, u.verified_at = True, me.id, utcnow()
        notify(u.id, "Your identity has been verified by SkillProof. A verified badge now shows on your report.",
               url_for("dashboard"), "success")
    elif action == "unverify_identity":
        u.identity_verified, u.verified_by_id, u.verified_at = False, None, None
    elif action == "verify_email":
        u.email_verified, u.email_verified_at = True, utcnow()
    elif action == "unlock":
        u.failed_logins, u.locked_until = 0, None
    elif action == "force_logout":
        u.session_version += 1
    else:
        return "Unknown action."
    log("admin_" + action, u.id, reason)
    return None


def register(app):

    @app.route("/admin")
    @login_required("admin")
    def admin():
        now = utcnow()
        signups, signups_pct = trend(User, User.created_at)
        assessed, assessed_pct = trend(Assessment, Assessment.created_at)
        evidence, evidence_pct = trend(Evidence, Evidence.uploaded_at)
        views, views_pct = trend(AuditLog, AuditLog.created_at, AuditLog.action == "profile_view_employer")
        kpis = [
            dict(label="Registered users", value=User.query.filter(User.status != "rejected").count(),
                 delta=signups_pct, sub=f"+{signups} this week", icon="users"),
            dict(label="Verified skills", value=Skill.query.filter_by(status="verified").count(),
                 delta=assessed_pct, sub=f"{assessed} assessments this week", icon="award"),
            dict(label="Evidence records", value=Evidence.query.count(),
                 delta=evidence_pct, sub=f"+{evidence} this week", icon="file"),
            dict(label="Employer profile views", value=AuditLog.query.filter_by(action="profile_view_employer").count(),
                 delta=views_pct, sub=f"{views} this week", icon="eye"),
        ]
        labels, signup_series = cumulative(User, User.created_at, 30)
        _, assess_series = cumulative(Assessment, Assessment.created_at, 30)
        _, evidence_series = cumulative(Evidence, Evidence.uploaded_at, 30)
        status_counts = dict(db.session.query(Skill.status, func.count()).group_by(Skill.status).all())
        role_counts = dict(db.session.query(User.role, func.count()).filter(User.status == "active")
                           .group_by(User.role).all())
        cat_counts = (db.session.query(Skill.category, func.count()).group_by(Skill.category)
                      .order_by(func.count().desc()).limit(6).all())
        total_assess = Assessment.query.count()
        passed = Assessment.query.filter_by(outcome="verified").count()
        sla = int(get_setting("assessment_sla_days") or 7)
        pending_skills = Skill.query.filter_by(status="pending").all()
        overdue = sum(1 for s in pending_skills if s.requested_at and (now - s.requested_at).days >= sla)
        # Assessor workload
        workload = (db.session.query(User, func.count(Assessment.id),
                                     func.sum(db.case((Assessment.outcome == "verified", 1), else_=0)))
                    .outerjoin(Assessment, Assessment.assessor_id == User.id)
                    .filter(User.role == "assessor", User.status == "active").group_by(User.id)
                    .order_by(func.count(Assessment.id).desc()).all())
        funnel = [
            ("Registered candidates", User.query.filter_by(role="candidate").count()),
            ("Built a skills profile", db.session.query(func.count(func.distinct(Skill.user_id))).scalar() or 0),
            ("Submitted evidence", db.session.query(func.count(func.distinct(Evidence.user_id))).scalar() or 0),
            ("Requested assessment", db.session.query(func.count(func.distinct(Skill.user_id)))
             .filter(Skill.status != "self_declared").scalar() or 0),
            ("Has a verified skill", db.session.query(func.count(func.distinct(Skill.user_id)))
             .filter(Skill.status == "verified").scalar() or 0),
            ("Shares report", User.query.filter_by(role="candidate", consent_share=True).count()),
        ]
        return render_template(
            "admin/dashboard.html", kpis=kpis,
            line=dict(labels=labels, series=[dict(name="Total users", values=signup_series),
                                             dict(name="Evidence records", values=evidence_series),
                                             dict(name="Assessments", values=assess_series)]),
            skill_status=status_counts, role_counts=role_counts, cat_counts=cat_counts,
            pass_rate=round(passed / total_assess * 100) if total_assess else None,
            queue=len(pending_skills), overdue=overdue, sla=sla, workload=workload, funnel=funnel,
            pending_users=User.query.filter_by(status="pending").order_by(User.created_at).limit(5).all(),
            pending_count=User.query.filter_by(status="pending").count(),
            open_appeals=Appeal.query.filter_by(status="open").order_by(Appeal.created_at).limit(5).all(),
            appeal_count=Appeal.query.filter_by(status="open").count(),
            activity=AuditLog.query.order_by(AuditLog.created_at.desc()).limit(10).all())

    # ---- users

    def users_query():
        q = request.args.get("q", "").strip()
        role = request.args.get("role", "")
        status = request.args.get("status", "")
        ver = request.args.get("verified", "")
        query = User.query
        if q:
            like = f"%{q}%"
            query = query.filter(or_(User.full_name.ilike(like), User.email.ilike(like),
                                     User.organisation.ilike(like)))
        if role in ROLES:
            query = query.filter(User.role == role)
        if status in ACCOUNT_STATUSES:
            query = query.filter(User.status == status)
        if ver == "identity":
            query = query.filter(User.identity_verified.is_(True))
        elif ver == "unverified":
            query = query.filter(User.identity_verified.is_(False))
        elif ver == "email_unverified":
            query = query.filter(User.email_verified.is_(False))
        sort = request.args.get("sort", "newest")
        order = {"newest": User.created_at.desc(), "oldest": User.created_at.asc(),
                 "name": User.full_name.asc(), "login": User.last_login_at.desc()}.get(sort, User.created_at.desc())
        return query.order_by(order)

    @app.route("/admin/users")
    @login_required("admin")
    def admin_users():
        pager = paginate(users_query(), per_page=15)
        counts = dict(db.session.query(User.status, func.count()).group_by(User.status).all())
        return render_template("admin/users.html", pager=pager, counts=counts, roles=ROLES, args=request.args)

    @app.route("/admin/users.csv")
    @login_required("admin")
    def admin_users_csv():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["id", "name", "email", "role", "status", "email_verified", "identity_verified",
                    "organisation", "location", "skills", "verified_skills", "joined", "last_login"])
        for u in users_query().all():
            w.writerow([u.id, u.full_name, u.email, u.role, u.status, u.email_verified, u.identity_verified,
                        u.organisation, u.location, len(u.skills), len(u.verified_skills),
                        u.created_at.date(), u.last_login_at or ""])
        log("users_exported", None, f"{request.query_string.decode()[:200]}")
        db.session.commit()
        return Response(buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=skillproof-users.csv"})

    @app.route("/admin/users/bulk", methods=["POST"])
    @login_required("admin")
    def admin_users_bulk():
        action = request.form.get("action")
        reason = request.form.get("reason", "").strip()[:500]
        ids = [to_int(i, None) for i in request.form.getlist("ids")]
        if action not in ("approve", "verify_identity", "verify_email", "suspend", "reactivate"):
            abort(400)
        done, errors = 0, []
        for u in User.query.filter(User.id.in_([i for i in ids if i])).all():
            err = apply_user_action(u, action, reason or "Bulk action by administrator")
            if err:
                errors.append(err)
            else:
                done += 1
        db.session.commit()
        if done:
            flash(f"{USER_ACTIONS[action].capitalize()}: {done} account(s).", "success")
        for e in errors[:3]:
            flash(e, "error")
        if not done and not errors:
            flash("Select at least one user.", "info")
        return redirect(safe_next(request.form.get("next"), url_for("admin_users")))

    @app.route("/admin/users/<int:uid>")
    @login_required("admin")
    def admin_user(uid):
        u = db.get_or_404(User, uid)
        activity = (AuditLog.query.filter(or_(AuditLog.subject_user_id == u.id, AuditLog.actor_id == u.id))
                    .order_by(AuditLog.created_at.desc()).limit(25).all())
        assessed = (Assessment.query.filter_by(assessor_id=u.id).order_by(Assessment.created_at.desc()).limit(10).all()
                    if u.role in ("assessor", "admin") else [])
        return render_template("admin/user.html", u=u, activity=activity, assessed=assessed, roles=ROLES)

    @app.route("/admin/users/<int:uid>/action", methods=["POST"])
    @login_required("admin")
    def admin_user_action(uid):
        u = db.get_or_404(User, uid)
        action = request.form.get("action")
        reason = request.form.get("reason", "").strip()[:500]
        if action == "role":
            role = request.form.get("role")
            if role not in ROLES:
                abort(400)
            if u.id == g.user.id:
                flash("You can't change your own role.", "error")
            elif role != u.role:
                old, u.role = u.role, role
                log("role_changed", u.id, f"{old} -> {role}")
                notify(u.id, f"Your SkillProof role is now: {role}.", url_for("dashboard"), "info")
                db.session.commit()
                flash(f"{u.full_name} is now {role}.", "success")
            return redirect(safe_next(request.form.get("next"), url_for("admin_user", uid=uid)))
        err = apply_user_action(u, action, reason)
        if err:
            flash(err, "error")
        else:
            db.session.commit()
            flash(f"{u.full_name}: {USER_ACTIONS[action]}.", "success")
        return redirect(safe_next(request.form.get("next"), url_for("admin_user", uid=uid)))

    @app.route("/admin/verifications")
    @login_required("admin")
    def admin_verifications():
        pending = User.query.filter_by(status="pending").order_by(User.created_at).all()
        identity = (User.query.filter(User.role == "candidate", User.status == "active",
                                      User.identity_verified.is_(False))
                    .join(Skill, Skill.user_id == User.id).distinct().order_by(User.created_at).all())
        job_requests = (User.query.filter_by(role="candidate", job_access="requested")
                        .order_by(User.job_access_at).all())
        return render_template("admin/verifications.html", pending=pending, identity=identity, job_requests=job_requests)

    # ---- assessments & appeals

    @app.route("/admin/assessments")
    @login_required("admin")
    def admin_assessments():
        outcome = request.args.get("outcome", "")
        cat = request.args.get("category", "")
        q = Assessment.query.join(Skill)
        if outcome in ("verified", "not_verified"):
            q = q.filter(Assessment.outcome == outcome)
        if cat in CATEGORIES:
            q = q.filter(Skill.category == cat)
        pager = paginate(q.order_by(Assessment.created_at.desc()), per_page=20)
        pending = Skill.query.filter_by(status="pending").order_by(Skill.requested_at).all()
        return render_template("admin/assessments.html", pager=pager, pending=pending, outcome=outcome, cat=cat,
                               sla=int(get_setting("assessment_sla_days") or 7))

    @app.route("/admin/appeals")
    @login_required("admin")
    def admin_appeals():
        appeals = Appeal.query.order_by(Appeal.status != "open", Appeal.created_at.desc()).all()
        return render_template("admin/appeals.html", appeals=appeals)

    @app.route("/admin/appeals/<int:apid>", methods=["POST"])
    @login_required("admin")
    def admin_appeal_resolve(apid):
        ap = db.get_or_404(Appeal, apid)
        decision = request.form.get("decision")
        note = request.form.get("resolution", "").strip()
        if ap.status != "open" or decision not in ("upheld", "rejected") or len(note) < 10:
            flash("Choose a decision and explain it (at least 10 characters).", "error")
            return redirect(url_for("admin_appeals"))
        ap.status, ap.resolution, ap.resolver_id, ap.resolved_at = decision, note[:2000], g.user.id, utcnow()
        skill = ap.assessment.skill
        if decision == "upheld":
            skill.status = "pending"
            skill.requested_at = utcnow()
        log("appeal_" + decision, ap.user_id, f"appeal={ap.id}")
        notify(ap.user_id, (f"Your appeal on “{skill.name}” was upheld. A different assessor will reassess it."
                            if decision == "upheld" else f"Your appeal on “{skill.name}” was not upheld. See the reasons."),
               url_for("skill_detail", sid=skill.id), "success" if decision == "upheld" else "warning")
        db.session.commit()
        flash("Appeal upheld: the skill is back in the queue for a different assessor."
              if decision == "upheld" else "Appeal rejected. The candidate can see your reasons.", "success")
        return redirect(url_for("admin_appeals"))

    # ---- audit & settings

    @app.route("/admin/audit")
    @login_required("admin")
    def admin_audit():
        action = request.args.get("action", "")
        q = request.args.get("q", "").strip()
        query = AuditLog.query
        if action:
            query = query.filter(AuditLog.action == action)
        if q:
            query = query.outerjoin(User, AuditLog.actor_id == User.id).filter(
                or_(User.full_name.ilike(f"%{q}%"), User.email.ilike(f"%{q}%"), AuditLog.detail.ilike(f"%{q}%")))
        actions = [a for (a,) in db.session.query(AuditLog.action).distinct().order_by(AuditLog.action)]
        pager = paginate(query.order_by(AuditLog.created_at.desc()), per_page=30)
        return render_template("admin/audit.html", pager=pager, actions=actions, action=action, q=q)

    @app.route("/admin/settings", methods=["GET", "POST"])
    @login_required("admin")
    def admin_settings():
        if request.method == "POST":
            f = request.form
            for key in ("registration_open", "employer_approval", "assessor_applications",
                        "candidate_approval", "require_email_verification"):
                set_setting(key, "1" if f.get(key) else "0")
            set_setting("assessment_sla_days", str(to_int(f.get("assessment_sla_days"), 7, 1, 60)))
            set_setting("announcement", f.get("announcement", "").strip()[:300])
            log("settings_changed", None, ", ".join(f"{k}={get_setting(k)}" for k in DEFAULT_SETTINGS)[:500])
            db.session.commit()
            flash("Platform settings saved.", "success")
            return redirect(url_for("admin_settings"))
        return render_template("admin/settings.html")
