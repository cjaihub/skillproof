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
    role = db.Column(db.String(20), nullable=False, default="candidate")
    headline = db.Column(db.String(160), default="")
    location = db.Column(db.String(120), default="")
    bio = db.Column(db.Text, default="")
    organisation = db.Column(db.String(160), default="")  # employers / assessors
    # Consent: nothing is visible to employers or via link unless this is True.
    consent_share = db.Column(db.Boolean, default=False, nullable=False)
    consent_at = db.Column(db.DateTime)
    share_token = db.Column(db.String(64), unique=True, default=lambda: secrets.token_urlsafe(16))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)

    skills = db.relationship("Skill", backref="owner", cascade="all, delete-orphan",
                             foreign_keys="Skill.user_id")
    experiences = db.relationship("Experience", backref="owner", cascade="all, delete-orphan",
                                  order_by="Experience.start_year.desc()")
    evidence = db.relationship("Evidence", backref="owner", cascade="all, delete-orphan")

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)

    @property
    def verified_skills(self):
        return [s for s in self.skills if s.status == "verified"]


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
    category = db.Column(db.String(80), default="")
    claimed_level = db.Column(db.Integer, default=3)
    years = db.Column(db.Integer, default=0)
    description = db.Column(db.Text, default="")
    status = db.Column(db.String(20), default="self_declared", nullable=False)
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
    created_at = db.Column(db.DateTime, default=utcnow)

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


class AuditLog(db.Model):
    """Accountability trail: who did what, and who viewed whose data."""
    __tablename__ = "audit_log"
    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    action = db.Column(db.String(60), nullable=False)
    subject_user_id = db.Column(db.Integer)
    detail = db.Column(db.String(500), default="")
    created_at = db.Column(db.DateTime, default=utcnow)

    actor = db.relationship("User", foreign_keys=[actor_id])
