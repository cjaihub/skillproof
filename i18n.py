"""Lightweight translations for SkillProof.

English strings in the templates are the message keys. Each other language has a JSON
catalogue in translations/<code>.json mapping English -> translation. Anything missing
falls back to English, so pages never break while translations are being completed.

Check coverage with:  python i18n.py
"""
import json
import re
from pathlib import Path

from flask import g, request, session

BASE = Path(__file__).resolve().parent
LANGUAGES = {
    # code: (native name, English name, text direction)
    "en": ("English", "English", "ltr"),
    "sw": ("Kiswahili", "Swahili", "ltr"),
    "fr": ("Français", "French", "ltr"),
    "ar": ("العربية", "Arabic", "rtl"),
    "so": ("Soomaali", "Somali", "ltr"),
    # Languages of refugee communities in Kenya and of the host communities
    "rw": ("Kinyarwanda", "Kinyarwanda", "ltr"),
    "rn": ("Ikirundi", "Kirundi", "ltr"),
    "am": ("አማርኛ", "Amharic", "ltr"),
    "ti": ("ትግርኛ", "Tigrinya", "ltr"),
    "om": ("Afaan Oromoo", "Oromo", "ltr"),
    "ln": ("Lingála", "Lingala", "ltr"),
    "luo": ("Dholuo", "Luo", "ltr"),
    "ki": ("Gĩkũyũ", "Kikuyu", "ltr"),
}
_coverage = {}
DEFAULT = "en"
_catalogs = {}


def catalog(code):
    if code not in _catalogs:
        path = BASE / "translations" / f"{code}.json"
        _catalogs[code] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return _catalogs[code]


def pick_language():
    """?lang= > saved choice (session/cookie) > browser Accept-Language > English."""
    code = request.args.get("lang")
    if code in LANGUAGES:
        session["lang"] = code
        return code
    code = session.get("lang") or request.cookies.get("sp_lang")
    if code in LANGUAGES:
        return code
    best = request.accept_languages.best_match(list(LANGUAGES))
    return best or DEFAULT


def current():
    return g.get("lang", DEFAULT)


def gettext(text, **kwargs):
    lang = current()
    out = text if lang == "en" else (catalog(lang).get(text) or text)
    return out.format(**kwargs) if kwargs else out


_ = gettext


def init_app(app):
    @app.before_request
    def _set_lang():
        g.lang = pick_language()

    @app.after_request
    def _remember(resp):
        if request.args.get("lang") in LANGUAGES:
            resp.set_cookie("sp_lang", request.args["lang"], max_age=365 * 86400, samesite="Lax",
                            secure=app.config.get("SESSION_COOKIE_SECURE", False))
        return resp

    @app.context_processor
    def _inject():
        lang = current()
        return dict(_=gettext, LANG=lang, LANG_DIR=LANGUAGES[lang][2], LANGUAGES=LANGUAGES, lang_coverage=coverage)


def coverage(code):
    """Share of the interface translated (0-100). Partial languages fall back to English."""
    if code == "en":
        return 100
    if code not in _coverage:
        keys = extract_strings()
        cat = catalog(code)
        _coverage[code] = round(100 * sum(1 for k in keys if k in cat) / max(1, len(keys)))
    return _coverage[code]


# ---------------------------------------------------------------- coverage check

def dynamic_strings():
    """Labels that are translated at runtime from code (statuses, levels, onboarding steps, password rules)."""
    from models import (ACCOUNT_STATUSES, APPLICATION_STATUSES, EVIDENCE_KINDS, JOB_STATUSES, JOB_TYPES, LEVELS,
                        SKILL_STATUSES)
    out = set()
    for d in (ACCOUNT_STATUSES, APPLICATION_STATUSES, EVIDENCE_KINDS, JOB_STATUSES, JOB_TYPES, LEVELS, SKILL_STATUSES):
        out |= set(d.values())
    out |= {"Confirm your email", "Complete your profile", "Add your skills", "Upload evidence", "Request an assessment",
            "Share your report", "at least 8 characters", "letters and numbers", "not containing your email",
            "not a common password"}
    return out


def extract_strings():
    pattern = re.compile(r"""_\(\s*(["'])((?:\\.|(?!\1).)*)\1""")
    found = set()
    for path in list((BASE / "templates").rglob("*.html")) + list(BASE.glob("*.py")) + list((BASE / "views").glob("*.py")):
        for m in pattern.finditer(path.read_text(encoding="utf-8")):
            found.add(m.group(2).replace("\\'", "'").replace('\\"', '"'))
    return found | dynamic_strings()


def review_path(code):
    return BASE / "translations" / f"{code}.machine.json"


def ai_translate(code, batch=70):
    """Draft missing translations for one language with Claude.

    Existing translations are given as a glossary so terms stay consistent. Every string drafted
    here is listed in translations/<code>.machine.json until a native speaker reviews it. Safe to
    stop and re-run: it only translates what is still missing.
    """
    import os
    from typing import List

    import anthropic
    from pydantic import BaseModel

    class Pair(BaseModel):
        source: str
        translation: str

    class Batch(BaseModel):
        items: List[Pair]

    native, english, direction = LANGUAGES[code]
    path = BASE / "translations" / f"{code}.json"
    cat = catalog(code)
    machine = set(json.loads(review_path(code).read_text(encoding="utf-8"))) if review_path(code).exists() else set()
    missing = sorted(k for k in extract_strings() if k not in cat)
    print(f"{english}: {len(missing)} strings to translate")
    if not missing:
        return
    # glossary: human-written translations of short, frequently used terms keep wording consistent
    glossary = {k: v for k, v in sorted(cat.items(), key=lambda kv: len(kv[0])) if k not in machine and len(k) < 40}
    glossary = dict(list(glossary.items())[:120])
    client = anthropic.Anthropic()
    ph = re.compile(r"\{\w+\}|\]\([^)]*\)")
    system = (
        f"You translate the user interface of SkillProof from English into {english} ({native}). SkillProof helps "
        "refugees and displaced professionals in Kenya get their skills assessed and find jobs; many users read with "
        "basic literacy, often on a phone. Rules:\n"
        "- Use simple, respectful, everyday words; short phrases for buttons and labels.\n"
        "- Keep placeholders like {name} and markdown link targets like (/skills) exactly as they are.\n"
        "- Keep the brand name SkillProof and technical names (Python, SQL, PDF, AI) unchanged.\n"
        "- Follow the glossary for terms it already covers, so the app is consistent.\n"
        f"- Text direction is {direction}; do not add direction marks.\n"
        "- Return every input string unchanged as 'source' with its translation.\n\n"
        f"Glossary (English -> {english}):\n" + json.dumps(glossary, ensure_ascii=False, indent=0))
    for i in range(0, len(missing), batch):
        chunk = missing[i:i + batch]
        try:
            resp = client.messages.parse(
                model=os.environ.get("SKILLPROOF_AI_MODEL", "claude-opus-5-5"), max_tokens=16000,
                output_config={"effort": "medium"},
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": json.dumps(chunk, ensure_ascii=False)}],
                output_format=Batch,
            )
        except anthropic.APIStatusError as e:
            print(f"  batch {i // batch + 1}: API error {e.status_code}; skipped (re-run to retry)")
            continue
        if resp.stop_reason != "end_turn" or resp.parsed_output is None:
            print(f"  batch {i // batch + 1}: stopped ({resp.stop_reason}); skipped (re-run to retry)")
            continue
        added = 0
        for p in resp.parsed_output.items:
            if p.source in chunk and p.translation.strip() and \
                    sorted(ph.findall(p.source)) == sorted(ph.findall(p.translation)):
                cat[p.source] = p.translation.strip()
                machine.add(p.source)
                added += 1
        path.write_text(json.dumps(cat, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        review_path(code).write_text(json.dumps(sorted(machine), ensure_ascii=False, indent=0), encoding="utf-8")
        print(f"  batch {i // batch + 1}/{(len(missing) + batch - 1) // batch}: {added}/{len(chunk)} added")
    _coverage.pop(code, None)
    print(f"Saved {path}. {len(machine)} machine-drafted strings are listed in {review_path(code).name} for review.")


if __name__ == "__main__":
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == "--translate":
        codes = [c for c in LANGUAGES if c != "en"] if sys.argv[2] == "all" else [sys.argv[2]]
        for c in codes:
            if c not in LANGUAGES:
                sys.exit(f"Unknown language code {c}. Add it to LANGUAGES first.")
            ai_translate(c)
        sys.exit(0)
    keys = extract_strings()
    print(f"{len(keys)} translatable strings")
    for code in LANGUAGES:
        if code == "en":
            continue
        cat = catalog(code)
        missing = sorted(k for k in keys if k not in cat)
        unused = sorted(k for k in cat if k not in keys)
        machine = json.loads(review_path(code).read_text()) if review_path(code).exists() else []
        print(f"  {code}: {len(keys) - len(missing)}/{len(keys)} translated" + (f", {len(unused)} unused" if unused else "")
              + (f", {len(machine)} awaiting native review" if machine else ""))
        for k in missing[:15]:
            print(f"     missing: {k}")
