"""Employer workspace: dashboard, talent search, shortlist."""
from datetime import timedelta

from flask import flash, g, redirect, render_template, request, url_for
from sqlalchemy import or_

from core import CATEGORIES, log, login_required, notify
from models import AuditLog, Shortlist, Skill, User, db, utcnow

VISIBLE = (User.role == "candidate", User.consent_share.is_(True), User.status == "active")


def register(app):

    @app.route("/employer")
    @login_required("employer", "admin")
    def employer_dashboard():
        shortlist = (Shortlist.query.filter_by(employer_id=g.user.id).join(User, Shortlist.candidate_id == User.id)
                     .filter(*VISIBLE).order_by(Shortlist.created_at.desc()).all())
        pool = User.query.filter(*VISIBLE)
        verified_pool = pool.join(Skill, Skill.user_id == User.id).filter(Skill.status == "verified").distinct()
        viewed = (AuditLog.query.filter_by(actor_id=g.user.id, action="profile_view_employer")
                  .order_by(AuditLog.created_at.desc()).limit(40).all())
        recent_ids = list(dict.fromkeys(v.subject_user_id for v in viewed))[:6]
        recent = [u for u in (db.session.get(User, i) for i in recent_ids)
                  if u and u.consent_share and u.status == "active"]
        newest = (verified_pool.order_by(User.created_at.desc()).limit(6).all())
        cats = (db.session.query(Skill.category, db.func.count(db.func.distinct(Skill.user_id)))
                .join(User, Skill.user_id == User.id).filter(*VISIBLE, Skill.status == "verified")
                .group_by(Skill.category).order_by(db.func.count().desc()).all())
        kpis = dict(pool=pool.count(), verified=verified_pool.count(), shortlist=len(shortlist),
                    viewed=len(set(v.subject_user_id for v in viewed)))
        return render_template("employer/dashboard.html", shortlist=shortlist, recent=recent, newest=newest,
                               kpis=kpis, cats=cats)

    @app.route("/talent")
    @login_required("employer", "admin")
    def talent():
        q = request.args.get("q", "").strip()
        cat = request.args.get("category", "")
        location = request.args.get("location", "").strip()
        min_level = request.args.get("level", "")
        verified_only = (request.args.get("verified") == "1") if "searched" in request.args else True
        sort = request.args.get("sort", "verified")
        query = db.session.query(User).join(Skill, Skill.user_id == User.id).filter(*VISIBLE)
        if verified_only:
            query = query.filter(Skill.status == "verified")
        if q:
            like = f"%{q}%"
            query = query.filter(or_(Skill.name.ilike(like), User.headline.ilike(like), User.bio.ilike(like)))
        if cat in CATEGORIES:
            query = query.filter(Skill.category == cat)
        if location:
            query = query.filter(User.location.ilike(f"%{location}%"))
        if min_level.isdigit():
            query = query.filter(Skill.claimed_level >= int(min_level))
        people = query.distinct().all()
        if sort == "name":
            people.sort(key=lambda p: p.full_name.lower())
        elif sort == "newest":
            people.sort(key=lambda p: p.created_at, reverse=True)
        else:
            people.sort(key=lambda p: (-len(p.verified_skills), p.full_name.lower()))
        saved = {s.candidate_id for s in Shortlist.query.filter_by(employer_id=g.user.id)}
        return render_template("employer/talent.html", people=people, q=q, cat=cat, location=location,
                               level=min_level, verified_only=verified_only, sort=sort, saved=saved)

    @app.route("/talent/<int:uid>")
    @login_required("employer", "admin")
    def talent_profile(uid):
        u = User.query.filter(User.id == uid, *VISIBLE).first_or_404()
        seen_today = AuditLog.query.filter(
            AuditLog.actor_id == g.user.id, AuditLog.subject_user_id == u.id,
            AuditLog.action == "profile_view_employer",
            AuditLog.created_at >= utcnow() - timedelta(days=1)).first()
        log("profile_view_employer", u.id, f"employer={g.user.organisation or g.user.email}")
        if g.user.role == "employer" and not seen_today:
            # Tell the candidate at most once per day per employer.
            notify(u.id, f"{g.user.organisation or 'An employer'} viewed your competency report.",
                   url_for("my_access_log"), "info")
        db.session.commit()
        entry = Shortlist.query.filter_by(employer_id=g.user.id, candidate_id=u.id).first()
        return render_template("employer/candidate.html", u=u, entry=entry)

    @app.route("/shortlist/<int:uid>", methods=["POST"])
    @login_required("employer")
    def shortlist_toggle(uid):
        u = User.query.filter(User.id == uid, *VISIBLE).first_or_404()
        entry = Shortlist.query.filter_by(employer_id=g.user.id, candidate_id=u.id).first()
        action = request.form.get("action", "toggle")
        if action == "note" and entry:
            entry.note = request.form.get("note", "").strip()[:500]
            flash("Note saved.", "success")
        elif entry:
            db.session.delete(entry)
            flash(f"{u.full_name} removed from your shortlist.", "info")
        else:
            db.session.add(Shortlist(employer_id=g.user.id, candidate_id=u.id))
            log("shortlisted", u.id, f"employer={g.user.organisation}")
            flash(f"{u.full_name} added to your shortlist.", "success")
        db.session.commit()
        nxt = request.form.get("next", "")
        return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("employer_dashboard"))
