"""AI features built on Claude: document import, evidence review and test generation.

Everything here is advisory: users accept each import suggestion, and human assessors make
every decision. When Claude isn't available (no ANTHROPIC_API_KEY, offline, SKILLPROOF_AI=off)
each feature degrades to a non-AI fallback so the app keeps working.
"""
import base64
import json
import os
import random
import re
import zipfile
from pathlib import Path
from typing import Literal

from flask import current_app
from pydantic import BaseModel

from core import CATEGORIES

MODEL = os.environ.get("SKILLPROOF_AI_MODEL", "claude-opus-5-5")
MAX_FILE_BYTES = 8 * 1024 * 1024
IMAGE_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}


class AIUnavailable(Exception):
    """Raised when Claude can't be used; callers fall back to a non-AI path."""


def enabled():
    return os.environ.get("SKILLPROOF_AI", "on") != "off"


def configured():
    """True when AI is switched on and credentials are present, so on-demand features can be offered."""
    return enabled() and bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


# ---------------------------------------------------------------- output schemas

Category = Literal["Software development", "IT support & networking", "Healthcare", "Teaching & training",
                   "Trades & vocational", "Business & finance", "Other"]


class ExperienceSuggestion(BaseModel):
    title: str
    organisation: str
    country: str
    start_year: int | None
    end_year: int | None
    description: str


class SkillSuggestion(BaseModel):
    name: str
    category: Category
    level: int  # 1 Beginner .. 5 Expert
    years: int
    evidence_note: str  # what in the document supports this skill


class Correction(BaseModel):
    field: str
    current_value: str
    suggested_value: str
    reason: str


class ProfileExtraction(BaseModel):
    document_type: Literal["cv", "certificate", "reference_letter", "work_sample", "id_document", "other"]
    summary: str
    headline: str | None
    location: str | None
    bio: str | None
    experiences: list[ExperienceSuggestion]
    skills: list[SkillSuggestion]
    corrections: list[Correction]
    warnings: list[str]


class CriterionSuggestion(BaseModel):
    criterion: Literal["knowledge", "practical", "evidence", "communication"]
    suggested_score: int
    rationale: str


class EvidenceReview(BaseModel):
    overall_summary: str
    criteria: list[CriterionSuggestion]
    strengths: list[str]
    concerns: list[str]
    authenticity_flags: list[str]
    questions_for_candidate: list[str]


class MCQ(BaseModel):
    question: str
    options: list[str]
    correct_index: int
    explanation: str


class GeneratedTest(BaseModel):
    questions: list[MCQ]
    short_questions: list[str]


# ---------------------------------------------------------------- Claude call

def _parse(system, content, schema, max_tokens=16000):
    """One structured-output request. Raises AIUnavailable on any credential/API problem."""
    if not enabled():
        raise AIUnavailable("AI is switched off")
    try:
        import anthropic
    except ImportError as e:
        raise AIUnavailable("anthropic package not installed") from e
    try:
        client = anthropic.Anthropic(max_retries=2, timeout=120.0)
        resp = client.beta.messages.parse(
            model=MODEL,
            max_tokens=max_tokens,
            output_config={"effort": "medium"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=system,
            messages=[{"role": "user", "content": content}],
            output_format=schema,
        )
    except anthropic.AuthenticationError as e:
        raise AIUnavailable("no valid Anthropic credentials") from e
    except anthropic.RateLimitError as e:
        raise AIUnavailable("AI is busy, try again shortly") from e
    except anthropic.APIConnectionError as e:
        raise AIUnavailable("cannot reach the AI service") from e
    except anthropic.APIStatusError as e:
        current_app.logger.error("AI API error %s: %s", e.status_code, e.message)
        raise AIUnavailable(f"AI service error ({e.status_code})") from e
    except TypeError as e:  # the SDK raises this when no credentials can be resolved
        if "auth" in str(e).lower():
            raise AIUnavailable("no Anthropic credentials configured") from e
        raise
    if resp.stop_reason == "refusal":
        raise AIUnavailable("the AI declined to process this content")
    if resp.stop_reason == "max_tokens" or resp.parsed_output is None:
        raise AIUnavailable("the AI response was incomplete")
    return resp.parsed_output


# ---------------------------------------------------------------- file handling

def read_docx_text(path):
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", "ignore")
    xml = re.sub(r"</w:p>", "\n", xml)
    return re.sub(r"<[^>]+>", "", xml)


def extract_text(path):
    ext = path.suffix.lower().lstrip(".")
    try:
        if ext == "pdf":
            from pypdf import PdfReader
            return "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages[:30])
        if ext == "docx":
            return read_docx_text(path)
        if ext == "txt":
            return path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:  # noqa: BLE001 - unreadable documents just produce no text
        current_app.logger.warning("Could not read %s: %s", path.name, e)
    return ""


def file_block(path, label=""):
    """Turn a stored file into a Claude content block (PDF, image or extracted text)."""
    ext = path.suffix.lower().lstrip(".")
    if path.stat().st_size > MAX_FILE_BYTES:
        return {"type": "text", "text": f"[{label}: file too large to include]"}
    if ext == "pdf":
        data = base64.standard_b64encode(path.read_bytes()).decode()
        return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data},
                "title": label or path.name}
    if ext in IMAGE_TYPES:
        data = base64.standard_b64encode(path.read_bytes()).decode()
        return {"type": "image", "source": {"type": "base64", "media_type": IMAGE_TYPES[ext], "data": data}}
    text = extract_text(path)
    return {"type": "text", "text": f"<document name=\"{label or path.name}\">\n{text[:60000] or '[no readable text]'}\n</document>"}


# ---------------------------------------------------------------- 1. document import

IMPORT_SYSTEM = """You help refugees and displaced professionals turn documents (CVs, certificates, reference \
letters, photos of their work) into an accurate skills profile on SkillProof.

Read the document and return suggestions. Rules:
- Only include facts that the document supports. Never invent employers, dates, qualifications or skills.
- Skills: specific, employable skills (e.g. "Python web development", "Electrical installation", "Midwifery"), not \
personality traits. Level 1-5 (1 Beginner, 2 Basic, 3 Competent, 4 Proficient, 5 Expert), estimated conservatively \
from years and responsibilities. evidence_note says what in the document supports the skill.
- Corrections: compare with the candidate's current profile (given below) and suggest fixes for spelling mistakes, \
inconsistent dates, vague headlines or missing details. Leave corrections empty when the profile already matches.
- headline: one line, max 120 characters. bio: 2-4 sentences in first person, max 600 characters. Use null when \
the document doesn't support a value.
- Write suggestions in the reply language named below; keep names of organisations and technologies as written.
- warnings: mention if the document looks like an identity document, passport or refugee card (the candidate should \
not upload those), if it is unreadable, or if it seems to belong to someone else. Never copy ID numbers, \
passport numbers, refugee numbers, phone numbers, emails or health information into any field."""


def profile_snapshot(u):
    return json.dumps({
        "headline": u.headline, "location": u.location, "bio": u.bio,
        "experiences": [{"title": e.title, "organisation": e.organisation, "country": e.country,
                         "start_year": e.start_year, "end_year": e.end_year} for e in u.experiences],
        "skills": [{"name": s.name, "category": s.category, "level": s.claimed_level, "years": s.years} for s in u.skills],
    }, ensure_ascii=False)


def import_document(path, user, original_name, reply_language="English"):
    """Returns (mode, result_dict). mode is 'ai' or 'basic'."""
    try:
        content = [
            file_block(path, original_name),
            {"type": "text", "text": f"Reply language: {reply_language}.\nCandidate's current profile (JSON):\n"
                                     f"{profile_snapshot(user)}\n\nCategories you may use: {', '.join(CATEGORIES)}."},
        ]
        result = _parse(IMPORT_SYSTEM, content, ProfileExtraction).model_dump()
        return "ai", _clean_extraction(result)
    except AIUnavailable as e:
        current_app.logger.info("Import using basic extraction: %s", e)
        return "basic", basic_extraction(path, user, str(e))


def _clean_extraction(r):
    for s in r["skills"]:
        s["level"] = max(1, min(5, int(s.get("level") or 3)))
        s["years"] = max(0, min(60, int(s.get("years") or 0)))
        s["name"] = s["name"][:120]
    for e in r["experiences"]:
        for k in ("start_year", "end_year"):
            if e.get(k) is not None and not (1950 <= e[k] <= 2100):
                e[k] = None
    r["headline"] = (r.get("headline") or "")[:160] or None
    r["bio"] = (r.get("bio") or "")[:2000] or None
    return r


SKILL_KEYWORDS = {
    "Software development": ["python", "django", "flask", "javascript", "typescript", "react", "node", "java", "php",
                             "sql", "mysql", "postgres", "html", "css", "git", "android", "kotlin", "c#", ".net"],
    "IT support & networking": ["networking", "cisco", "network", "windows server", "active directory", "it support",
                                "helpdesk", "troubleshooting", "linux", "firewall", "tcp/ip", "router"],
    "Healthcare": ["nursing", "nurse", "midwife", "midwifery", "pharmacy", "clinical", "first aid", "laboratory",
                   "patient care", "community health"],
    "Teaching & training": ["teaching", "teacher", "lesson planning", "curriculum", "tutor", "training", "mathematics",
                            "english language"],
    "Trades & vocational": ["electrical", "electrician", "solar", "plumbing", "welding", "carpentry", "masonry",
                            "tailoring", "mechanic", "driving", "construction", "hairdressing", "catering", "cooking"],
    "Business & finance": ["accounting", "bookkeeping", "excel", "quickbooks", "finance", "budget", "sales", "marketing",
                           "customer service", "procurement", "project management", "administration"],
}


def basic_extraction(path, user, reason):
    """Offline fallback: keyword and date matching on the document's text."""
    text = extract_text(path)
    warnings = [f"AI reading was not available ({reason}). These are basic keyword suggestions: please check them."]
    if not text.strip():
        warnings.append("No text could be read from this file. Photos and scanned documents need AI reading.")
    low = text.lower()
    existing = {s.name.lower() for s in user.skills}
    skills = []
    for cat, words in SKILL_KEYWORDS.items():
        for w in words:
            if re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", low) and w not in existing:
                name = w.upper() if len(w) <= 3 else w.title() if w.islower() else w
                skills.append({"name": name, "category": cat, "level": 3, "years": 0,
                               "evidence_note": "Mentioned in the document"})
                existing.add(w)
    experiences = []
    for line in text.splitlines():
        m = re.search(r"((?:19|20)\d{2})\s*(?:-|–|to)\s*((?:19|20)\d{2}|present|current|now)", line, re.I)
        if m and 6 < len(line.strip()) < 160:
            title = re.sub(r"\(?\s*" + re.escape(m.group(0)) + r"\s*\)?", "", line).strip(" ,-–|:")
            end = None if not m.group(2)[0].isdigit() else int(m.group(2))
            if title:
                experiences.append({"title": title[:160], "organisation": "", "country": "",
                                    "start_year": int(m.group(1)), "end_year": end, "description": ""})
    return {"document_type": "other", "summary": f"Text extracted from {path.suffix.upper().lstrip('.')} file.",
            "headline": None, "location": None, "bio": None, "experiences": experiences[:8],
            "skills": skills[:12], "corrections": [], "warnings": warnings}


# ---------------------------------------------------------------- 2. evidence review for assessors

REVIEW_SYSTEM = """You are an assistant to a human skills assessor on SkillProof, a platform that verifies skills of \
refugees and displaced professionals who often lost their certificates. The assessor makes the decision; you give \
an advisory review.

Score each criterion 0-5 based only on the material provided:
- knowledge: understands the concepts, tools and standards of the skill
- practical: can do the work, shown by the practical task, test answers or work samples
- evidence: the evidence is relevant, consistent and credible
- communication: can explain their work and decisions clearly
Pass mark is 12/20 with no criterion below 2. Missing documents alone are not a reason to score low on \
knowledge or practical ability: many candidates lost papers when displaced; judge the work shown.
Flag possible authenticity problems (inconsistent dates or names, text copied from elsewhere, documents that don't \
match the claimed skill) neutrally, as things for the assessor to check, never as accusations. Suggest 1-3 \
questions the assessor could ask the candidate. Be concise and specific. Write in English."""


def review_evidence(skill, upload_dir):
    """Returns an EvidenceReview dict. Raises AIUnavailable."""
    u = skill.owner
    test = next((t for t in skill.tests if t.submitted_at), None)
    parts = [f"Skill: {skill.name} ({skill.category}). Claimed level: {skill.claimed_level}/5, {skill.years} years.",
             f"Candidate's description: {skill.description or '(none)'}",
             f"Practical task response:\n{skill.task_response or '(none)'}"]
    if test:
        qs, ans = json.loads(test.questions_json), json.loads(test.answers_json or "{}")
        parts.append(f"Online test: {test.mcq_score}/{test.mcq_total} multiple-choice correct.")
        for i, q in enumerate(qs.get("short_questions", [])):
            parts.append(f"Short answer question: {q}\nAnswer: {ans.get(f's{i}', '(blank)')}")
    parts.append("Work history: " + "; ".join(f"{e.title} at {e.organisation or '?'} {e.start_year or ''}-{e.end_year or 'present'}"
                                             for e in u.experiences) or "none")
    content = [{"type": "text", "text": "\n\n".join(parts)}]
    files = [e for e in skill.evidence if e.stored_name][:5]
    for e in files:
        p = Path(upload_dir) / e.stored_name
        if p.exists():
            content.append({"type": "text", "text": f"Evidence: {e.title} ({e.kind}). {e.description or ''}"})
            content.append(file_block(p, e.title))
    links = [f"{e.title}: {e.link}" for e in skill.evidence if e.link]
    if links:
        content.append({"type": "text", "text": "Linked evidence (not opened): " + "; ".join(links)})
    result = _parse(REVIEW_SYSTEM, content, EvidenceReview).model_dump()
    for c in result["criteria"]:
        c["suggested_score"] = max(0, min(5, int(c["suggested_score"])))
    return result


# ---------------------------------------------------------------- 3. skills test

QUESTION_BANK = {
    "Software development": [
        ("What does an HTTP 404 status code mean?", ["Server error", "Resource not found", "Unauthorised", "Redirect"], 1),
        ("Which statement about Git is true?", ["A commit can only contain one file", "A branch lets you work on changes separately", "Git requires an internet connection", "Pull requests are part of Git itself"], 1),
        ("What is SQL injection?", ["A way to speed up queries", "Inserting untrusted input into a query so it runs as code", "A database backup method", "An index type"], 1),
        ("Why write automated tests?", ["To make code run faster", "To catch regressions when code changes", "To replace code reviews", "Tests are only for large teams"], 1),
        ("Which data structure gives fast lookup by key?", ["Linked list", "Hash map / dictionary", "Stack", "Queue"], 1),
    ],
    "IT support & networking": [
        ("A user can reach websites by IP address but not by name. What is most likely failing?", ["DHCP", "DNS", "The network cable", "The printer"], 1),
        ("What does a DHCP server do?", ["Encrypts traffic", "Gives devices IP addresses automatically", "Blocks viruses", "Stores files"], 1),
        ("Which command shows the route packets take to a host?", ["ping", "tracert / traceroute", "ipconfig", "netstat"], 1),
        ("What is the safest first step before changing a production server?", ["Restart it", "Take a backup / snapshot", "Disable the firewall", "Email all users"], 1),
        ("Which address is a private IPv4 address?", ["8.8.8.8", "192.168.1.10", "1.1.1.1", "172.217.0.1"], 1),
    ],
    "Healthcare": [
        ("What is the most effective way to prevent spreading infection between patients?", ["Wearing a mask only", "Hand hygiene before and after contact", "Opening windows", "Using antibiotics"], 1),
        ("A partograph is used to…", ["Record a child's vaccinations", "Monitor the progress of labour", "Measure blood sugar", "Track medication stock"], 1),
        ("Normal resting heart rate for an adult is about…", ["30–50 bpm", "60–100 bpm", "120–150 bpm", "160–200 bpm"], 1),
        ("What should you do first if a patient is unresponsive?", ["Give water", "Check responsiveness and call for help", "Wait 10 minutes", "Give medication"], 1),
        ("Why must patient records be kept confidential?", ["It saves paper", "To protect the patient's privacy and trust", "It is optional", "Only for children"], 1),
    ],
    "Teaching & training": [
        ("What is formative assessment?", ["The final exam", "Checking learning during teaching to adjust it", "Grading homework only", "A school inspection"], 1),
        ("A good learning objective is…", ["Vague and broad", "Specific and measurable", "Only about the teacher", "Kept secret"], 1),
        ("How can you support learners at different levels in one class?", ["Teach only the fastest", "Differentiate tasks and support", "Ignore the difference", "Give everyone the same test only"], 1),
        ("What is an 'exit ticket'?", ["A permission slip", "A short task at the end of a lesson to check understanding", "A detention", "A timetable"], 1),
        ("Positive classroom behaviour is best encouraged by…", ["Clear expectations and praise", "Only punishment", "No rules", "Long lectures"], 0),
    ],
    "Trades & vocational": [
        ("Before working on an electrical circuit you should…", ["Work faster", "Isolate the supply and test it is dead", "Wear gloves only", "Switch on the lights"], 1),
        ("What does PPE stand for?", ["Personal protective equipment", "Power plant electricity", "Primary project estimate", "Pipe pressure equipment"], 0),
        ("Why is earthing (grounding) important?", ["It saves electricity", "It protects people from electric shock", "It makes cables cheaper", "It is decorative"], 1),
        ("Measure twice, cut once means…", ["Work slowly", "Check measurements before cutting to avoid waste", "Always cut two pieces", "Use two tools"], 1),
        ("In a solar system, the charge controller…", ["Stores energy", "Protects batteries from over/under charging", "Converts DC to AC", "Cleans panels"], 1),
    ],
    "Business & finance": [
        ("In double-entry bookkeeping every transaction…", ["Is recorded once", "Has equal debit and credit entries", "Is only recorded at year end", "Is optional"], 1),
        ("A budget variance is…", ["A type of tax", "The difference between planned and actual figures", "A bank account", "An invoice"], 1),
        ("Which document requests payment from a customer?", ["Receipt", "Invoice", "Purchase order", "Payslip"], 1),
        ("Cash flow measures…", ["Profit only", "Money coming in and going out over time", "Number of employees", "Stock levels"], 1),
        ("Why keep receipts and records?", ["They are decorative", "For accountability, audits and tax", "Only for large companies", "They are not needed"], 1),
    ],
    "Other": [
        ("A customer is unhappy with your work. What is the best first step?", ["Argue", "Listen and understand the problem", "Ignore them", "Refund immediately without asking"], 1),
        ("Good time management means…", ["Doing everything at once", "Prioritising tasks and planning", "Working only at night", "Avoiding deadlines"], 1),
        ("When you don't know how to do a task you should…", ["Guess", "Ask or check reliable guidance", "Skip it", "Blame others"], 1),
        ("Teamwork works best when…", ["One person does everything", "Roles and communication are clear", "No one talks", "Everyone works alone"], 1),
        ("Safety rules at work are…", ["Optional", "There to protect you and others", "Only for managers", "Only for new staff"], 1),
    ],
}
SHORT_QUESTIONS = [
    "Describe a difficult problem you solved using this skill. What did you do and what was the result?",
    "How would you explain a key part of this skill to someone new to it?",
]

TEST_SYSTEM = """Write a short skills test for a candidate on SkillProof, a platform verifying skills of refugees \
and displaced professionals. Create exactly 6 multiple-choice questions (4 options each, one correct, \
correct_index 0-3) that test practical, real-world knowledge of the skill at the claimed level, not trivia or \
brand-specific facts, plus exactly 2 open short-answer questions asking the candidate to explain how they would \
handle realistic situations. Use plain, simple language: many candidates read in a second language. Write the \
questions in the language named by the user. Vary which option is correct."""


def build_test(skill, reply_language="English"):
    """Returns (source, questions dict). Correct answers stay server-side."""
    try:
        t = _parse(TEST_SYSTEM, [{"type": "text", "text": f"Skill: {skill.name}. Category: {skill.category}. "
                                  f"Claimed level: {skill.claimed_level}/5. Language: {reply_language}."}],
                   GeneratedTest, max_tokens=8000)
        mcq = [q.model_dump() for q in t.questions if len(q.options) >= 2 and 0 <= q.correct_index < len(q.options)][:8]
        if len(mcq) >= 4 and t.short_questions:
            return "ai", {"mcq": mcq, "short_questions": t.short_questions[:3]}
    except AIUnavailable as e:
        current_app.logger.info("Skills test from question bank: %s", e)
    bank = list(QUESTION_BANK.get(skill.category, QUESTION_BANK["Other"]))
    random.shuffle(bank)
    mcq = []
    for q, options, correct in bank:
        order = list(range(len(options)))
        random.shuffle(order)
        mcq.append({"question": q, "options": [options[i] for i in order], "correct_index": order.index(correct),
                    "explanation": ""})
    return "bank", {"mcq": mcq, "short_questions": SHORT_QUESTIONS}


# ---------------------------------------------------------------- job matching

def match_score(job, candidate):
    """0-100: how well a candidate's skills cover a job's required skills. Verified skills count fully."""
    req = [r.lower() for r in job.skills_list]
    if not req:
        return 100 if any(s.category == job.category and s.status == "verified" for s in candidate.skills) else 50
    total = 0.0
    for r in req:
        best = 0.0
        for s in candidate.skills:
            name = s.name.lower()
            if r in name or name in r or set(r.split()) & set(name.split()) - {"and", "&", "of"}:
                weight = 1.0 if s.status == "verified" else 0.4
                level = (s.latest_assessment.assessed_level if s.status == "verified" and s.latest_assessment
                         and s.latest_assessment.assessed_level else s.claimed_level)
                if level < (job.min_level or 1):
                    weight *= 0.7
                best = max(best, weight)
        total += best
    return round(total / len(req) * 100)
