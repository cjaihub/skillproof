"""Database models for SkillProof.

Works with MySQL in production (DATABASE_URL=mysql+pymysql://...) and SQLite
for quick local development.
"""
import secrets
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


ROLES = ("candidate", "assessor", "employer", "admin")

# Account lifecycle. Employers and assessors start "pending" until an admin approves them.
ACCOUNT_STATUSES = {
    "pending": "Pending approval",
    "active": "Active",
    "rejected": "Rejected",
    "suspended": "Suspended",
}

# Skill verification states. Self-declared skills are always shown as such,
# kept apart from independently assessed ones.
SKILL_STATUSES = {
    "self_declared": "Self-declared",
    "pending": "Awaiting assessment",
    "verified": "Independently assessed",
    "not_verified": "Not yet verified",
}

LEVELS = {1: "Beginner", 2: "Basic", 3: "Competent", 4: "Proficient", 5: "Expert"}

# Clear, published criteria every assessor scores against (0-5 each).
CRITERIA = {
    "knowledge": "Technical knowledge: understands the concepts, tools and standards of the skill",
    "practical": "Practical ability: can do the work, shown by the practical task or work samples",
    "evidence": "Evidence quality: the evidence is relevant, consistent and credible",
    "communication": "Communication: can explain their work and decisions clearly",
}
PASS_MARK = 12  # out of 20; plus no single criterion below 2

EVIDENCE_KINDS = {
    "certificate": "Certificate or qualification",
    "portfolio": "Portfolio",
    "work_sample": "Work sample",
    "reference": "Reference or letter",
    "other": "Other",
}


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="candidate", index=True)
    headline = db.Column(db.String(160), default="")
    location = db.Column(db.String(120), default="")
    phone = db.Column(db.String(40), default="")
    bio = db.Column(db.Text, default="")
    organisation = db.Column(db.String(160), default="")  # employers / assessors
    website = db.Column(db.String(255), default="")
    expertise = db.Column(db.String(255), default="")      # assessors: areas they can assess
    # Account lifecycle & admin verification
    status = db.Column(db.String(20), default="active", nullable=False, index=True)
    status_reason = db.Column(db.String(500), default="")
    email_verified = db.Column(db.Boolean, default=False, nullable=False)
    email_verified_at = db.Column(db.DateTime)
    identity_verified = db.Column(db.Boolean, default=False, nullable=False)
    verified_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    verified_at = db.Column(db.DateTime)
    # Security
    failed_logins = db.Column(db.Integer, default=0, nullable=False)
    locked_until = db.Column(db.DateTime)
    session_version = db.Column(db.Integer, default=1, nullable=False)
    last_login_at = db.Column(db.DateTime)
    # Job access: candidates ask an admin to make them "job-ready" once they have verified skills.
    job_access = db.Column(db.String(20), default="none", nullable=False)  # none/requested/granted/declined
    job_access_note = db.Column(db.String(500), default="")
    job_access_at = db.Column(db.DateTime)
    # Consent: nothing is visible to employers or via link unless this is True.
    consent_share = db.Column(db.Boolean, default=False, nullable=False)
    consent_at = db.Column(db.DateTime)
    share_token = db.Column(db.String(64), unique=True, default=lambda: secrets.token_urlsafe(16))
    created_at = db.Column(db.DateTime, default=utcnow, index=True)

    skills = db.relationship("Skill", backref="owner", cascade="all, delete-orphan",
                             foreign_keys="Skill.user_id")
    experiences = db.relationship("Experience", backref="owner", cascade="all, delete-orphan",
                                  order_by="Experience.start_year.desc()")
    evidence = db.relationship("Evidence", backref="owner", cascade="all, delete-orphan")
    notifications = db.relationship("Notification", backref="user", cascade="all, delete-orphan",
                                    order_by="Notification.created_at.desc()", lazy="dynamic")
    verified_by = db.relationship("User", remote_side=[id], foreign_keys=[verified_by_id])

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)
        self.session_version = (self.session_version or 0) + 1  # log out other sessions

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)

    @property
    def is_active(self):
        return self.status == "active"

    @property
    def initials(self):
        parts = [p for p in self.full_name.split() if p[:1].isalpha()]
        return ("".join(p[0] for p in parts[:2]) or "?").upper()

    @property
    def first_name(self):
        parts = [p for p in self.full_name.split() if not p.endswith(".")]
        return parts[0] if parts else self.full_name

    @property
    def verified_skills(self):
        return [s for s in self.skills if s.status == "verified"]

    @property
    def status_label(self):
        return ACCOUNT_STATUSES.get(self.status, self.status)

    def competence_areas(self, only=None):
        """Skills grouped into competence areas (one per category), strongest areas first.

        Each area: category, verified skills (with their latest assessment), declared skills,
        level (highest assessed level, else highest claimed), average score and criteria averages.
        """
        areas = {}
        for s in self.skills:
            if only and s.category != only:
                continue
            a = areas.setdefault(s.category or "Other", {"category": s.category or "Other", "verified": [],
                                                          "declared": [], "years": 0})
            (a["verified"] if s.status == "verified" else a["declared"]).append(s)
            a["years"] = max(a["years"], s.years or 0)
        out = []
        for a in areas.values():
            assessed = [s.latest_assessment for s in a["verified"] if s.latest_assessment]
            a["assessed_level"] = max((x.assessed_level or 0 for x in assessed), default=0)
            a["claimed_level"] = max((s.claimed_level for s in a["declared"] + a["verified"]), default=0)
            a["avg_score"] = round(sum(x.total for x in assessed) / len(assessed), 1) if assessed else None
            a["criteria"] = ({k: round(sum(getattr(x, f"score_{k}") for x in assessed) / len(assessed), 1)
                              for k in ("knowledge", "practical", "evidence", "communication")} if assessed else {})
            a["verified"].sort(key=lambda s: -(s.latest_assessment.total if s.latest_assessment else 0))
            out.append(a)
        out.sort(key=lambda a: (-len(a["verified"]), -(a["avg_score"] or 0), -a["claimed_level"]))
        return out

    @property
    def total_years(self):
        spans = [((e.end_year or utcnow().year) - e.start_year) for e in self.experiences if e.start_year]
        return sum(max(0, s) for s in spans)

    @property
    def completeness(self):
        """Profile completeness 0-100 for candidates."""
        checks = [bool(self.headline), bool(self.location), len(self.bio or "") >= 80,
                  bool(self.experiences), bool(self.skills), bool(self.evidence),
                  any(s.status != "self_declared" for s in self.skills), self.email_verified]
        return round(sum(checks) / len(checks) * 100)

    @property
    def unread_count(self):
        return self.notifications.filter_by(read=False).count()


class Experience(db.Model):
    __tablename__ = "experiences"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    title = db.Column(db.String(160), nullable=False)
    organisation = db.Column(db.String(160), default="")
    country = db.Column(db.String(80), default="")
    start_year = db.Column(db.Integer)
    end_year = db.Column(db.Integer)  # None = current
    description = db.Column(db.Text, default="")


class Skill(db.Model):
    __tablename__ = "skills"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(80), default="", index=True)
    claimed_level = db.Column(db.Integer, default=3)
    years = db.Column(db.Integer, default=0)
    description = db.Column(db.Text, default="")
    status = db.Column(db.String(20), default="self_declared", nullable=False, index=True)
    # Practical assessment submission (answer text or link to a repo/video)
    task_response = db.Column(db.Text, default="")
    requested_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=utcnow)

    evidence = db.relationship("Evidence", backref="skill")
    assessments = db.relationship("Assessment", backref="skill", cascade="all, delete-orphan",
                                  order_by="Assessment.created_at.desc()")

    @property
    def latest_assessment(self):
        return self.assessments[0] if self.assessments else None

    @property
    def status_label(self):
        return SKILL_STATUSES.get(self.status, self.status)


class Evidence(db.Model):
    __tablename__ = "evidence"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    skill_id = db.Column(db.Integer, db.ForeignKey("skills.id", ondelete="SET NULL"))
    title = db.Column(db.String(160), nullable=False)
    kind = db.Column(db.String(30), default="other")
    description = db.Column(db.Text, default="")
    link = db.Column(db.String(500), default="")
    stored_name = db.Column(db.String(120))  # random name on disk, never user-supplied
    original_name = db.Column(db.String(255))
    uploaded_at = db.Column(db.DateTime, default=utcnow)


class Assessment(db.Model):
    __tablename__ = "assessments"
    id = db.Column(db.Integer, primary_key=True)
    skill_id = db.Column(db.Integer, db.ForeignKey("skills.id"), nullable=False)
    assessor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    score_knowledge = db.Column(db.Integer, nullable=False)
    score_practical = db.Column(db.Integer, nullable=False)
    score_evidence = db.Column(db.Integer, nullable=False)
    score_communication = db.Column(db.Integer, nullable=False)
    assessed_level = db.Column(db.Integer)
    outcome = db.Column(db.String(20), nullable=False)  # verified / not_verified
    comments = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, index=True)

    assessor = db.relationship("User", foreign_keys=[assessor_id])
    appeals = db.relationship("Appeal", backref="assessment", cascade="all, delete-orphan")

    @property
    def total(self):
        return (self.score_knowledge + self.score_practical
                + self.score_evidence + self.score_communication)

    @property
    def reference(self):
        return f"SP-{self.created_at:%Y}-{self.id:05d}"


class Appeal(db.Model):
    __tablename__ = "appeals"
    id = db.Column(db.Integer, primary_key=True)
    assessment_id = db.Column(db.Integer, db.ForeignKey("assessments.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default="open")  # open / upheld / rejected
    resolution = db.Column(db.Text, default="")
    resolver_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=utcnow)
    resolved_at = db.Column(db.DateTime)

    user = db.relationship("User", foreign_keys=[user_id])
    resolver = db.relationship("User", foreign_keys=[resolver_id])


class Shortlist(db.Model):
    """An employer's saved candidates."""
    __tablename__ = "shortlist"
    id = db.Column(db.Integer, primary_key=True)
    employer_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    candidate_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    note = db.Column(db.String(500), default="")
    created_at = db.Column(db.DateTime, default=utcnow)
    __table_args__ = (db.UniqueConstraint("employer_id", "candidate_id"),)

    candidate = db.relationship("User", foreign_keys=[candidate_id])


class Notification(db.Model):
    __tablename__ = "notifications"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = db.Column(db.String(20), default="info")  # info / success / warning
    message = db.Column(db.String(300), nullable=False)
    link = db.Column(db.String(300), default="")
    read = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)


JOB_TYPES = {"full_time": "Full-time", "part_time": "Part-time", "contract": "Contract",
             "internship": "Internship", "volunteer": "Volunteer"}
JOB_STATUSES = {"pending": "Awaiting approval", "open": "Open", "rejected": "Not approved", "closed": "Closed"}
APPLICATION_STATUSES = {"applied": "Applied", "shortlisted": "Shortlisted", "interview": "Interview",
                        "offered": "Offer made", "hired": "Hired", "declined": "Not selected", "withdrawn": "Withdrawn"}


class DocImport(db.Model):
    """A document a candidate uploaded for AI to read and turn into profile suggestions."""
    __tablename__ = "doc_imports"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    stored_name = db.Column(db.String(120), nullable=False)
    original_name = db.Column(db.String(255), nullable=False)
    mode = db.Column(db.String(10), default="ai")       # ai / basic (offline text extraction)
    status = db.Column(db.String(12), default="ready")  # ready / applied / discarded
    result_json = db.Column(db.Text, default="{}")
    created_at = db.Column(db.DateTime, default=utcnow)


class AiReview(db.Model):
    """Advisory AI summary of a skill's evidence and answers, for the human assessor."""
    __tablename__ = "ai_reviews"
    id = db.Column(db.Integer, primary_key=True)
    skill_id = db.Column(db.Integer, db.ForeignKey("skills.id", ondelete="CASCADE"), nullable=False, index=True)
    requested_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    model = db.Column(db.String(60), default="")
    result_json = db.Column(db.Text, default="{}")
    created_at = db.Column(db.DateTime, default=utcnow)


class SkillTest(db.Model):
    """Online skills test taken before requesting assessment. Correct answers never leave the server."""
    __tablename__ = "skill_tests"
    id = db.Column(db.Integer, primary_key=True)
    skill_id = db.Column(db.Integer, db.ForeignKey("skills.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    source = db.Column(db.String(10), default="bank")  # ai / bank
    questions_json = db.Column(db.Text, nullable=False)
    answers_json = db.Column(db.Text, default="{}")
    mcq_score = db.Column(db.Integer)
    mcq_total = db.Column(db.Integer)
    started_at = db.Column(db.DateTime, default=utcnow)
    submitted_at = db.Column(db.DateTime)

    skill = db.relationship("Skill", backref=db.backref("tests", cascade="all, delete-orphan",
                                                        order_by="SkillTest.started_at.desc()"))


class Job(db.Model):
    __tablename__ = "jobs"
    id = db.Column(db.Integer, primary_key=True)
    employer_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = db.Column(db.String(160), nullable=False)
    category = db.Column(db.String(80), default="Other")
    location = db.Column(db.String(120), default="")
    remote = db.Column(db.Boolean, default=False)
    job_type = db.Column(db.String(20), default="full_time")
    salary = db.Column(db.String(120), default="")
    description = db.Column(db.Text, default="")
    required_skills = db.Column(db.String(500), default="")  # comma-separated
    min_level = db.Column(db.Integer, default=3)
    status = db.Column(db.String(12), default="pending", index=True)
    review_note = db.Column(db.String(500), default="")
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime, default=utcnow)
    approved_at = db.Column(db.DateTime)

    employer = db.relationship("User", foreign_keys=[employer_id])
    applications = db.relationship("Application", backref="job", cascade="all, delete-orphan",
                                   order_by="Application.created_at.desc()")

    @property
    def skills_list(self):
        return [s.strip() for s in (self.required_skills or "").split(",") if s.strip()]


class Application(db.Model):
    __tablename__ = "applications"
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    candidate_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    cover_note = db.Column(db.Text, default="")
    match = db.Column(db.Integer, default=0)
    status = db.Column(db.String(12), default="applied")
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow)
    __table_args__ = (db.UniqueConstraint("job_id", "candidate_id"),)

    candidate = db.relationship("User", foreign_keys=[candidate_id])


class ContentTranslation(db.Model):
    """Cache of machine translations of user-written text (profiles, job ads, feedback)."""
    __tablename__ = "content_translations"
    id = db.Column(db.Integer, primary_key=True)
    source_hash = db.Column(db.String(64), nullable=False)
    lang = db.Column(db.String(8), nullable=False)
    text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)
    __table_args__ = (db.UniqueConstraint("source_hash", "lang"),)


class Setting(db.Model):
    """Platform settings editable by admins."""
    __tablename__ = "settings"
    key = db.Column(db.String(60), primary_key=True)
    value = db.Column(db.String(500), default="")


class AuditLog(db.Model):
    """Accountability trail: who did what, and who viewed whose data."""
    __tablename__ = "audit_log"
    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    action = db.Column(db.String(60), nullable=False, index=True)
    subject_user_id = db.Column(db.Integer, index=True)
    detail = db.Column(db.String(500), default="")
    ip = db.Column(db.String(64), default="")
    created_at = db.Column(db.DateTime, default=utcnow, index=True)

    actor = db.relationship("User", foreign_keys=[actor_id])
