# AI features

SkillProof uses **Claude** through the official `anthropic` Python SDK. AI is **optional and advisory**: every
feature has a non-AI fallback, and no AI output becomes a decision without a person accepting it.

## Configuration

| Variable | Default | Effect |
|---|---|---|
| `ANTHROPIC_API_KEY` | unset | Turns AI on. Without it, every feature uses its fallback. |
| `SKILLPROOF_AI_MODEL` | `claude-opus-5-5` | Model for all features. |
| `SKILLPROOF_AI` | `on` | Set to `off` to force fallbacks even when a key is set. |

Keep the key in `.env` (ignored by git), never in code.

## Features

| Feature | Where | AI behaviour | Fallback |
|---|---|---|---|
| **Onboarding assistant** | `views/assistant.py`, `/api/assistant` | Streams answers in the user's language at `effort: low`. The system prompt is cached; context is role, progress, page and language only. | **Guide mode**: keyword-matched answers, translated |
| **Document import** | `ai.import_document`, `/import` | Reads a PDF, image, Word or text file and returns a `ProfileExtraction`: skills with level and confidence, experiences, headline, summary, **corrections**. Detects and refuses identity documents. | `basic_extraction`: pypdf / docx text, skill keywords and year ranges |
| **Skills test** | `ai.build_test`, `/skills/<id>/test` | Writes 6 multiple-choice questions plus 2 written prompts for the exact skill and level (`GeneratedTest`). | Built-in `QUESTION_BANK` per category, plus `SHORT_QUESTIONS` |
| **Evidence review** | `ai.review_evidence`, `/review/<id>/ai` | Reads evidence files, test answers and the task answer; suggests a 0–5 score per criterion with reasons, strengths, concerns, things to check and interview questions (`EvidenceReview`). | Button hidden; the assessor reviews by hand |
| **Content translation** | `views/translate.py`, `/api/translate` | Translates user-written text into the reader's language, keeping names and reference codes. Cached. | 503; the original text is kept |
| **UI translation** | `i18n.py --translate` (CLI) | Drafts missing interface strings using existing human translations as a glossary. Keeps placeholders. | Strings fall back to English |
| **Job matching** | `ai.match_score` | *Not an LLM.* A deterministic score: verified skills count fully, self-declared 0.4, below the minimum level ×0.7. | n/a |

## Implementation notes

- **Structured outputs.** `ai._parse()` calls `client.beta.messages.parse(...)` with a Pydantic model as the output format,
  so results are typed and validated. Any API, credential or network error, or a refusal, raises `AIUnavailable`, which callers catch to switch to the fallback.
- **Resilience.** Calls send `betas=["server-side-fallback-2026-07-01"]` with `fallbacks="default"`, and
  `max_retries` / `timeout` are set on the client.
- **Refusals.** `stop_reason == "refusal"` is handled: the chat appends a polite message; the parse calls raise `AIUnavailable`.
- **Prompt caching.** Long, fixed system prompts use `cache_control: ephemeral`.
- **Streaming.** The chat uses `client.beta.messages.stream` and forwards text as SSE. Anything that needs the database
  is computed *before* the response starts streaming, because the request context is gone by then.

## Privacy

- The assistant never receives a user's name, email, phone or files, only role, onboarding progress, current page and language.
- Document import and evidence review send the selected file(s) to Anthropic for that request only. Users are told
  this before uploading, and are told not to upload ID or refugee registration documents.
- Chats are not stored by SkillProof. Imports and AI reviews are stored so the user or assessor can come back to them.
- Rate limits: chat 20 / 10 min, translation 30 / 10 min per session.

## Human in the loop

| AI suggests | A person decides |
|---|---|
| Imported skills and corrections | The candidate ticks what to keep |
| Criterion scores in the evidence review | The assessor enters their own scores and writes their own feedback |
| Generated test questions | Auto-marked, but the assessor sees every answer and decides the outcome |
| Machine-translated UI strings | Listed in `translations/<code>.machine.json` for native review |

## Cost

All features use a single model. Rough guide on `claude-opus-5-5`:

| Action | Typical cost |
|---|---|
| Assistant message | well under US$0.01 (low effort, cached prompt) |
| Document import / evidence review | a few cents per document |
| Translating the full UI into 12 languages | about US$10, once |

Use `SKILLPROOF_AI_MODEL` to pick a cheaper model for high-volume deployments.
