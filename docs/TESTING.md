# Testing

Two scripts, with no extra test dependencies. Both use Flask's test client against a temporary SQLite database, so your
own data is never touched, and both run AI features in fallback mode, so they never call the API.

## End-to-end flow: `test_flow.py`

```bash
python test_flow.py
```
This runs **246 checks** through the whole platform as each role:

- Registration wizard, password rules, email verification, lockout, reset
- CSRF rejection, approval gate for pending employers and assessors, role-based access denials
- Profile, experience, skills, evidence upload and download permissions
- Skills test (bank fallback), practical task, submit, assessor scoring and the pass rule, appeals and reassignment
- Consent, share link, rotated link, `?area=` reports, access log
- Document import (basic mode), job access request and grant, job posting and approval, match score, apply, pipeline, withdraw
- Admin dashboard, bulk actions, CSV export, audit log, settings
- Every language renders (including RTL), the assistant in guide mode, `/api/translate` caching, validation and 503 behaviour
- Data export and account deletion

It exits non-zero if any check fails.

## Link crawler: `test_links.py`

```bash
python test_links.py
```
This signs in as each demo role, follows every internal link and form-free page it can reach, and fails on any server error (5xx)
or 404. Language variants (`?lang=`) are skipped to keep it fast.

## Manual checks before a release

- Phone width (375 px), tablet (768 px), desktop
- Dark and system themes
- Arabic (RTL)
- Print preview of `/report`
- With an `ANTHROPIC_API_KEY`: chat, import a real CV, an AI test, an AI review, content translation
