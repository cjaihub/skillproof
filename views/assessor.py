"""Assessor workspace: dashboard, queue, scoring."""
import json

from flask import abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import func

import ai
from core import daily_counts, get_setting, log, login_required, notify, task_for, to_int
from models import CRITERIA, PASS_MARK, AiReview, Assessment, Skill, db, utcnow


def blocked_assessors(skill):
    """Assessors whose decision on this skill was overturned on appeal may not reassess it."""
    return {a.assessor_id for a in skill.assessments if any(ap.status == "upheld" for ap in a.appeals)}


def register(app):

    @app.route("/review")
    @login_required("assessor", "admin")
    def review_queue():
        cat = request.args.get("category", "")
        q = Skill.query.filter(Skill.status == "pending", Skill.user_id != g.user.id)
        if cat:
            q = q.filter(Skill.category == cat)
        pending = [s for s in q.order_by(Skill.requested_at).all() if g.user.id not in blocked_assessors(s)]
        mine_q = Assessment.query.filter_by(assessor_id=g.user.id)
        total = mine_q.count()
        passed = mine_q.filter_by(outcome="verified").count()
        month = mine_q.filter(Assessment.created_at >= utcnow().replace(day=1, hour=0, minute=0, second=0)).count()
        sla = int(get_setting("assessment_sla_days") or 7)
        now = utcnow()
        overdue = sum(1 for s in pending if s.requested_at and (now - s.requested_at).days >= sla)
        labels, values = daily_counts(Assessment.created_at, 14, (Assessment.assessor_id == g.user.id,))
        avg = db.session.query(func.avg(Assessment.score_knowledge + Assessment.score_practical
                                        + Assessment.score_evidence + Assessment.score_communication)
                               ).filter(Assessment.assessor_id == g.user.id).scalar()
        kpis = dict(queue=len(pending), total=total, month=month, overdue=overdue,
                    pass_rate=round(passed / total * 100) if total else None,
                    avg=round(avg, 1) if avg else None)
        mine = mine_q.order_by(Assessment.created_at.desc()).limit(10).all()
        return render_template("assessor/dashboard.html", pending=pending, mine=mine, kpis=kpis, sla=sla,
                               cat=cat, chart=dict(labels=labels, data=values),
                               outcome=dict(passed=passed, failed=total - passed))

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
        if g.user.id in blocked_assessors(s) and s.status == "pending":
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
            elif not f.get("no_conflict"):
                flash("Please confirm you have no conflict of interest with this candidate.", "error")
            else:
                total = sum(scores.values())
                passed = total >= PASS_MARK and min(scores.values()) >= 2
                a = Assessment(skill_id=s.id, assessor_id=g.user.id,
                               score_knowledge=scores["knowledge"], score_practical=scores["practical"],
                               score_evidence=scores["evidence"], score_communication=scores["communication"],
                               assessed_level=to_int(f.get("assessed_level"), 3, 1, 5) if passed else None,
                               outcome="verified" if passed else "not_verified", comments=comments[:3000])
                s.status = a.outcome
                db.session.add(a)
                log("assessment_completed", s.user_id, f"skill={s.id} outcome={a.outcome} total={total}")
                notify(s.user_id, (f"Great news: “{s.name}” has been independently verified ({total}/20)."
                                   if passed else f"“{s.name}” was assessed but not yet verified. See the feedback."),
                       url_for("skill_detail", sid=s.id), "success" if passed else "warning")
                db.session.commit()
                flash(f"Assessment saved: {'verified' if passed else 'not verified'} ({total}/20).", "success")
                return redirect(url_for("review_queue"))
        log("evidence_reviewed", s.user_id, f"skill={s.id}")
        db.session.commit()
        latest = AiReview.query.filter_by(skill_id=s.id).order_by(AiReview.created_at.desc()).first()
        test = next((t for t in s.tests if t.submitted_at), None)
        return render_template("assessor/review.html", s=s, task=task_for(s), test=test,
                               test_q=json.loads(test.questions_json) if test else None,
                               test_a=json.loads(test.answers_json or "{}") if test else None,
                               ai_review=json.loads(latest.result_json) if latest else None,
                               ai_review_at=latest.created_at if latest else None, ai_on=ai.enabled())
