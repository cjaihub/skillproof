"""Onboarding assistant: answers questions about SkillProof in the user's language.

Uses Claude through the Anthropic SDK when credentials are available (ANTHROPIC_API_KEY or an
`ant auth login` profile). Without them, or if the API is unreachable, it falls back to a built-in
guide so the widget always works (useful for offline demos).

Privacy: only the user's role, onboarding progress, current page path and language are sent as
context, never their name, email or files. SkillProof does not store chat transcripts.
"""
import json
import os
import time

from flask import Response, current_app, g, jsonify, request, session, stream_with_context, url_for

from i18n import LANGUAGES, current, gettext as _

MODEL = os.environ.get("SKILLPROOF_AI_MODEL", "claude-opus-5-5")
AI_ENABLED = os.environ.get("SKILLPROOF_AI", "on") != "off"
MAX_TURNS = 12
MAX_CHARS = 1500
RATE_LIMIT = (20, 600)  # 20 messages per 10 minutes per browser session

SYSTEM_PROMPT = """You are the SkillProof Assistant, a friendly onboarding guide inside SkillProof, a web platform \
that helps refugees and displaced professionals in Kenya get their skills recognised by employers.

How SkillProof works (candidates):
1. Register: free account in about two minutes; email confirmation; nothing is shared until the user turns sharing on.
2. Build a profile: headline, location, summary and work history at /profile. Work before displacement, volunteering \
and informal work all count.
3. Add skills at /skills/new: name, category, claimed level (Beginner, Basic, Competent, Proficient, Expert), years.
4. Add evidence at /evidence: PDF, images, Word, text or zip up to 10 MB, or links. Lost certificates are common; photos \
of work, code links, references and letters help. Evidence is private: employers never see files. Never upload ID \
documents, passports or refugee registration numbers - they are not needed.
5. Request an assessment from a skill's page: answer a short practical task for the field. A vetted assessor scores \
four published criteria from 0 to 5 (technical knowledge, practical ability, evidence quality, communication). \
Pass mark: 12/20 or more with no criterion below 2. Usually within 7 days. Assessors must give written reasons.
6. Disagree with a result? Appeal from the skill page; an administrator reviews and, if upheld, a different assessor reassesses.
7. Share: on /report the candidate gives consent, then verified employers can find them and they get a link they can \
switch off or replace at any time. /my-access-log shows who viewed their profile.

Employers register, wait for admin approval (to protect candidates from fake recruiters), then search verified talent \
at /talent, filter by skill, category, location and level, and shortlist candidates with private notes. They see \
assessment results, never evidence files, email or phone.
Assessors apply at registration with their organisation and expertise; an administrator approves them.
Accounts: /login, /register, /forgot (password reset by email link), /account (change password, download data, delete \
account). Accounts lock for 15 minutes after 5 failed logins. Data rights follow Kenya's Data Protection Act, 2019.

How to answer:
- Reply in the language named in the context below, in plain, simple words: many users read in a second language. If the user writes in a different language (for example Kinyarwanda, Kirundi, Amharic, Tigrinya, Oromo, Lingala, Dholuo, Gikuyu, Turkana, Nuer or Dinka), reply in the language they write in.
- Be brief: 2 to 5 short sentences or a short numbered list. End with one clear next step.
- When pointing to a page, use a markdown link with a path from the list above, for example [Add a skill](/skills/new). \
Only use these paths; never invent URLs or external links.
- Use the user's onboarding progress in the context to suggest what to do next.
- Never ask for passwords, ID numbers, refugee registration numbers, health information or bank details. If a user \
shares them, tell them not to and continue.
- You cannot see or change their account, approve anything, assess skills or promise jobs. Say so when asked.
- For legal, immigration, asylum, resettlement, health or safety questions, say you can only help with SkillProof and \
suggest contacting UNHCR or a trusted refugee-support organisation. In an emergency, tell them to contact local \
emergency services.
- Stay on topic: SkillProof, job readiness, describing skills and gathering evidence. Politely decline anything else."""


# ---------------------------------------------------------------- context

def progress_steps(u):
    if not u or u.role != "candidate":
        return []
    return [
        ("Confirm your email", u.email_verified),
        ("Complete your profile", bool(u.headline and len(u.bio or "") >= 80)),
        ("Add your skills", bool(u.skills)),
        ("Upload evidence", bool(u.evidence)),
        ("Request an assessment", any(s.status != "self_declared" for s in u.skills)),
        ("Share your report", u.consent_share),
    ]


def context_block(page):
    u = g.get("user")
    lang = LANGUAGES[current()][1]
    lines = [f"Reply language: {lang}.", f"Current page: {page or '/'}."]
    if not u:
        lines.append("The visitor is not logged in.")
    else:
        lines.append(f"Logged in as a {u.role}. Account status: {u.status}. Email confirmed: {'yes' if u.email_verified else 'no'}.")
        steps = progress_steps(u)
        if steps:
            lines.append("Onboarding progress: " + "; ".join(f"{name}: {'done' if ok else 'not yet'}" for name, ok in steps) + ".")
            lines.append(f"Skills: {len(u.skills)} ({len(u.verified_skills)} independently assessed). Evidence items: {len(u.evidence)}.")
    return "\n".join(lines)


# ---------------------------------------------------------------- offline guide

def guide_answer(text):
    """Keyword-based onboarding guide used when Claude isn't available. Answers are translated."""
    t = (text or "").lower()
    u = g.get("user")

    def has(*words):
        return any(w in t for w in words)

    if has("next", "what should", "start", "begin", "how do i get", "anza", "nifanye", "ninaanzaje", "ifuatayo",
           "commencer", "suivant", "que dois-je", "par où", "ابدأ", "التالي", "ماذا أفعل", "كيف أبدأ",
           "bilow", "xiga", "maxaan sameeyaa", "sidee u bilaabaa") or not t.strip():
        steps = progress_steps(u)
        if not u:
            return _("Welcome! Start by creating a free account: [Create account](/register). It takes about two minutes, and nothing is shared until you choose to share it.")
        todo = [name for name, ok in steps if not ok]
        links = {"Confirm your email": "/account", "Complete your profile": "/profile", "Add your skills": "/skills/new",
                 "Upload evidence": "/evidence", "Request an assessment": "/skills", "Share your report": "/report"}
        if u.role != "candidate":
            return _("Your dashboard shows everything you need. Open it here: [Dashboard](/dashboard).")
        if not todo:
            return _("Great work: you've completed every onboarding step! Keep your profile up to date and check [Who viewed me](/my-access-log).")
        return _("Your next step: {step}. Open it here: [{step}]({link}).", step=_(todo[0]), link=links[todo[0]])
    if has("password", "login", "log in", "nenosiri", "mot de passe", "كلمة", "erayga sirta", "lock"):
        return _("Forgot your password? Use [Reset password](/forgot) and we'll email you a secure link. After 5 wrong attempts an account locks for 15 minutes.")
    if has("certificate", "lost", "cheti", "certificat", "perdu", "شهادة", "شهادات", "shahaado", "evidence", "ushahidi", "preuve", "دليل", "caddayn"):
        return _("No certificates? That's common. Upload what you still have: photos of your work, code links, reference letters or a description of projects. Evidence is private and employers never see files. Add it here: [Evidence](/evidence).")
    if has("assess", "test", "task", "tathmini", "évaluation", "تقييم", "qiimeyn", "score", "pass mark"):
        return _("To get a skill assessed: open the skill, answer the short practical task and submit. An assessor scores 4 criteria from 0 to 5. You pass with 12/20 and no criterion below 2, usually within 7 days. Start here: [My skills](/skills).")
    if has("appeal", "disagree", "rufaa", "contester", "استئناف", "racfaan", "wrong"):
        return _("If you disagree with a result, open the skill and choose \"Appeal\". Explain what was missed. An administrator reviews it, and if upheld, a different assessor reassesses. See your skills: [My skills](/skills).")
    if has("share", "employer", "job", "kazi", "emploi", "وظيفة", "shaqo", "report", "ripoti", "rapport", "تقرير", "warbixin"):
        if u and u.role == "employer":
            return _("Search verified candidates here: [Find talent](/talent). You can filter by skill, category and location, and shortlist people with private notes.")
        return _("When you're ready, turn on sharing on your report page. Verified employers can then find you, and you get a link you can switch off at any time: [Competency report](/report).")
    if has("privacy", "my data", "safe", "faragha", "données", "خصوصية", "xog", "delete", "passport", "refugee number"):
        return _("Your profile is private until you turn on sharing. Employers never see your files, email or phone. Never upload ID documents or refugee numbers: they aren't needed. Read more: [Privacy](/privacy).")
    if has("assessor", "mtathmini", "évaluateur", "مقيّم", "qiimeeye"):
        return _("Professionals can apply to become assessors when registering. An administrator reviews every application. Apply here: [Become an assessor](/register?role=assessor).")
    if has("skill", "ujuzi", "compétence", "مهارة", "xirfad", "profile", "wasifu", "profil", "ملف"):
        return _("Add each skill with your level and years of experience, then add a short description of where you used it: [Add a skill](/skills/new). Complete your profile too: [My profile](/profile).")
    if has("language", "lugha", "langue", "لغة", "luqad", "translate"):
        return _("SkillProof is available in many languages, including Kiswahili, Français, العربية, Soomaali, Kinyarwanda, Ikirundi, አማርኛ and more. Use the globe button at the top of the page to change language. You can also write to me in your own language.")
    if has("human", "person", "contact", "help", "msaada", "aide", "مساعدة", "caawin"):
        return _("I'm an automated guide. For help from a person, contact the refugee-support organisation that referred you, or UNHCR. For anything about SkillProof, ask me here.")
    return _("I can help you register, build your profile, add evidence, get assessed and share your report. Try asking \"What should I do next?\"")


# ---------------------------------------------------------------- routes

def _rate_limited():
    now = time.time()
    window = [t for t in session.get("ai_times", []) if now - t < RATE_LIMIT[1]]
    if len(window) >= RATE_LIMIT[0]:
        session["ai_times"] = window
        return True
    window.append(now)
    session["ai_times"] = window
    return False


def _clean_history(raw):
    """Keep the last MAX_TURNS valid messages, alternating and starting with the user."""
    msgs = []
    for m in raw if isinstance(raw, list) else []:
        role, content = (m or {}).get("role"), (m or {}).get("content")
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            msgs.append({"role": role, "content": content.strip()[:MAX_CHARS]})
    msgs = msgs[-MAX_TURNS:]
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    merged = []
    for m in msgs:  # merge accidental consecutive same-role messages
        if merged and merged[-1]["role"] == m["role"]:
            merged[-1]["content"] += "\n" + m["content"]
        else:
            merged.append(m)
    return merged if merged and merged[-1]["role"] == "user" else []


def _sse(obj):
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def _stream_claude(messages, context, refusal_text):
    """Yield text chunks from Claude. Raises on credential/network problems so we can fall back."""
    import anthropic

    client = anthropic.Anthropic(max_retries=1, timeout=60.0)
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=4096,  # short chat answers; keeps cost per message bounded
        output_config={"effort": "low"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=[
            {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": context},
        ],
        messages=messages,
    ) as stream:
        for text in stream.text_stream:
            yield text
        final = stream.get_final_message()
        if final.stop_reason == "refusal":
            yield "\n\n" + refusal_text


def register(app):

    @app.route("/api/assistant", methods=["POST"])
    def assistant_chat():
        data = request.get_json(silent=True) or {}
        messages = _clean_history(data.get("messages"))
        page = str(data.get("page", ""))[:200]
        if not messages:
            return jsonify(error="empty"), 400
        if _rate_limited():
            return jsonify(error=_("You've sent a lot of messages. Please wait a few minutes and try again.")), 429
        question = messages[-1]["content"]
        # Work out everything that needs the database or request now: the response streams after
        # the request has finished, when the user object can no longer load related rows.
        context = context_block(page)
        fallback = guide_answer(question)
        refusal_text = _("Sorry, I can't help with that. I can answer questions about using SkillProof.")
        app_obj = current_app._get_current_object()

        def generate():
            mode = "ai" if AI_ENABLED else "guide"
            sent_any = False
            if AI_ENABLED:
                try:
                    import anthropic  # noqa: F401
                    for chunk in _stream_claude(messages, context, refusal_text):
                        if not sent_any:
                            yield _sse({"mode": "ai"})
                        sent_any = True
                        yield _sse({"t": chunk})
                except ImportError:
                    mode = "guide"
                except Exception as e:  # noqa: BLE001 - any API/credential problem -> offline guide
                    import anthropic
                    if isinstance(e, anthropic.RateLimitError):
                        app_obj.logger.warning("Assistant rate limited by API")
                    elif isinstance(e, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
                        app_obj.logger.warning("Assistant: no valid Anthropic credentials; using offline guide")
                    elif isinstance(e, anthropic.APIConnectionError):
                        app_obj.logger.warning("Assistant: cannot reach the Anthropic API; using offline guide")
                    elif isinstance(e, anthropic.APIStatusError):
                        app_obj.logger.error("Assistant API error %s: %s", e.status_code, e.message)
                    elif "authentication" in str(e).lower():
                        app_obj.logger.info("Assistant: no Anthropic credentials configured; using offline guide")
                    else:
                        app_obj.logger.warning("Assistant unavailable (%s: %s); using offline guide", type(e).__name__, e)
                    mode = "guide"
            if mode == "guide" and not sent_any:
                yield _sse({"mode": "guide"})
                yield _sse({"t": fallback})
            yield _sse({"done": True})

        resp = Response(stream_with_context(generate()), mimetype="text/event-stream")
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["X-Accel-Buffering"] = "no"
        return resp
