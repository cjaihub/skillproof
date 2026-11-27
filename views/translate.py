"""Translate user-written content (profiles, job ads, assessor feedback) into the reader's language.

Pages mark user content with data-tr; the "Translate" bar sends those texts here. Results are cached
per (text, language), so each text is translated once. Uses Claude; without an API key the endpoint
answers 503 and the page keeps the original text.
"""
import hashlib
import time

from flask import jsonify, request, session
from pydantic import BaseModel

import ai
from i18n import LANGUAGES
from i18n import gettext as _
from models import ContentTranslation, db

MAX_TEXTS = 40
MAX_CHARS = 4000
RATE = (30, 600)  # 30 requests per 10 minutes per session


class Translated(BaseModel):
    translations: list[str]


def _key(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def translate_texts(texts, lang):
    """Return translations in the same order. Raises ai.AIUnavailable."""
    native, english, _dir = LANGUAGES[lang]
    keys = [_key(t) for t in texts]
    cached = {c.source_hash: c.text for c in
              ContentTranslation.query.filter(ContentTranslation.lang == lang, ContentTranslation.source_hash.in_(keys))}
    todo = [t for t, k in zip(texts, keys, strict=False) if k not in cached]
    if todo:
        system = (f"Translate each text into {english} ({native}) for a reader on SkillProof, a skills platform for "
                  "refugees and displaced professionals. Keep meaning, tone and line breaks; use plain, simple words. "
                  "Keep names of people, organisations, places, technologies and reference codes (like SP-2026-00042) "
                  f"unchanged. If a text is already in {english}, return it unchanged. Return exactly one translation per "
                  "input, in the same order.")
        content = [{"type": "text", "text": "\n".join(f"<text id=\"{i}\">{t}</text>" for i, t in enumerate(todo))}]
        result = ai._parse(system, content, Translated, max_tokens=16000)
        if len(result.translations) != len(todo):
            raise ai.AIUnavailable("translation count mismatch")
        for src, out in zip(todo, result.translations, strict=False):
            k = _key(src)
            if k not in cached:
                db.session.add(ContentTranslation(source_hash=k, lang=lang, text=out.strip() or src))
                cached[k] = out.strip() or src
        db.session.commit()
    return [cached[k] for k in keys]


def register(app):

    @app.route("/api/translate", methods=["POST"])
    def translate_content():
        data = request.get_json(silent=True) or {}
        lang = data.get("lang")
        texts = data.get("texts")
        if lang not in LANGUAGES or not isinstance(texts, list) or not texts:
            return jsonify(error="bad request"), 400
        texts = [str(t)[:MAX_CHARS] for t in texts[:MAX_TEXTS]]
        now = time.time()
        recent = [t for t in session.get("tr_times", []) if now - t < RATE[1]]
        if len(recent) >= RATE[0]:
            return jsonify(error=_("You've sent a lot of messages. Please wait a few minutes and try again.")), 429
        session["tr_times"] = recent + [now]
        if lang == "en" and all(t.isascii() for t in texts):
            return jsonify(translations=texts)
        try:
            return jsonify(translations=translate_texts(texts, lang))
        except ai.AIUnavailable as e:
            app.logger.info("Content translation unavailable: %s", e)
            return jsonify(error=_("Automatic translation of user-written text is not available yet on this server.")), 503
