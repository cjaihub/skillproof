# SkillProof: Digital Skills Recognition and Validation Platform

A working prototype that helps refugees and displaced people **record, evidence, validate and share**
their professional skills, so employers can trust competencies gained outside formal systems.

**Stack:** HTML5 · CSS3 · JavaScript · Python 3 / Flask · MySQL (SQLite for quick local dev) · Git

---

## Quick start (local)

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python seed.py --reset             # optional: load demo accounts and data
python app.py                      # open http://127.0.0.1:5050 (port 5000 is often taken by macOS AirPlay)
```

Without `DATABASE_URL` the app uses a local SQLite file (`skillproof.db`), so nothing else needs installing.

### Using MySQL
1. Run `schema.sql` in MySQL to create the database and user.
2. `cp .env.example .env` and set `DATABASE_URL=mysql+pymysql://user:pass@host:3306/skillproof?charset=utf8mb4`
   and a real `SECRET_KEY`.
3. `python seed.py --reset` (optional), then `python app.py`. Tables are created automatically.

### Demo accounts (after `python seed.py`)
All use the `DEMO_PASSWORD` in [seed.py](seed.py). **Demo only: remove before real use.**

| Role | Email | What to try |
|---|---|---|
| Candidate | `amina@skillproof.test` | Two verified skills, sharing on: view report & share link |
| Candidate | `jean@skillproof.test` | Skill awaiting assessment |
| Candidate | `nyaruach@skillproof.test` | Not-verified skill with an open appeal |
| Assessor | `assessor@skillproof.test` | Assess Jean's networking skill |
| Assessor | `assessor2@skillproof.test` | Second assessor (blocked from reassessing after an upheld appeal) |
| Employer | `employer@skillproof.test` | Search verified talent |
| Admin | `admin@skillproof.test` | Metrics, roles, appeals, audit log |

### 5-minute demo script
1. **Register** a new candidate → add a skill → upload evidence → answer the practical task → *Submit for assessment*.
2. Log in as **assessor** → *Review queue* → score the 4 criteria (live pass/fail total) → write feedback → save.
3. Back as **candidate** → *My report* → tick consent → *Turn on sharing* → copy the link, open it in a private window.
4. Log in as **employer** → *Find talent* → open the profile (the candidate sees this in *Who viewed my profile?*).
5. As **Nyaruach**, see the appeal; as **admin** → *Appeals* → uphold → the skill returns to the queue for a *different* assessor.
6. **Admin** → *Overview* shows the project success indicators.

---

## How it maps to the proposal

| Proposal feature | Where |
|---|---|
| User registration | `/register`: candidate or employer. Assessors are appointed by an admin |
| Skills profile | `/profile` (headline, summary, work history) and `/skills/new` (skill, category, level, years) |
| Evidence submission | `/evidence`: files (PDF/image/Word/zip, 10 MB) or links, linked to a skill |
| Skills assessment | Practical task per category → assessor scores 4 published criteria (0–5). Pass = 12/20 with no criterion below 2 |
| Verification dashboard | `/review`: assessor queue with evidence, task response and history |
| Digital competency report | `/report`: printable / save-as-PDF, with assessment references |
| Employer access | `/talent`: search consenting candidates, filter by verified skills |
| Shareable profile | `/p/<token>`: consent-gated link that can be revoked or regenerated |
| Success indicators | `/admin`: users, profiles, evidence, assessments, reports shared, employer views |

### Ethics, security & data protection (Kenya Data Protection Act, 2019)
- **Password hashing**: Werkzeug salted hashes (scrypt/pbkdf2), never plaintext.
- **Role-based access control**: candidate / assessor / employer / admin, checked on every route.
- **Consent before sharing**: off by default; explicit consent checkbox; timestamped; withdraw any time; rotate link.
- **Secure evidence storage**: stored outside `static/` under random filenames, served only after a permission
  check to the owner, assessors and admins. **Employers never see evidence files.** File type and size limits.
- **Clear criteria and reviewer accountability**: published criteria; assessor name and organisation recorded on every decision;
  written feedback required; assessors can't assess themselves.
- **Self-declared vs assessed**: shown separately everywhere, with distinct badges and report sections.
- **Appeals and corrections**: candidates appeal with reasons; admin resolves with written reasons; upheld appeals go
  to a different assessor.
- **Data subject rights**: download all my data (JSON), see who accessed my data, delete account (files removed too).
- **Audit log**: assessments, role and consent changes, evidence and profile views.
- **Data minimisation**: users are told not to upload ID or refugee registration numbers.
- **CSRF tokens** on every form, HttpOnly and SameSite session cookies, open-redirect-safe login.

Before a real launch: register with the ODPC as a data controller/processor, do a Data Protection Impact
Assessment, use HTTPS (`SESSION_COOKIE_SECURE=1`), put uploads in encrypted object storage, add email verification and
rate limiting, and have the privacy notice reviewed by a lawyer.

---

## Deployment

Netlify serves static files only, so it **cannot run Flask or MySQL**. Recommended options:

- **Simplest:** deploy the whole Flask app (it serves its own HTML/CSS/JS) on **Render**, **Railway**, **PythonAnywhere**
  or **Fly.io**, with a managed MySQL database (Railway MySQL, Aiven, PlanetScale-compatible, or AWS RDS).
  Start command: `gunicorn app:app`. Set `SECRET_KEY`, `DATABASE_URL`, `SESSION_COOKIE_SECURE=1`, and a persistent `UPLOAD_FOLDER`.
- **If Netlify is required:** host a static landing page on Netlify and link or redirect it to the Flask app's URL.
  A fully separate frontend would mean turning the routes into a JSON API, which is a larger change than the MVP needs.

## Project structure
```
app.py              routes, access control, assessment logic
models.py           database models, criteria, statuses
seed.py             demo data
templates/          HTML (Jinja2) pages
static/css/style.css  responsive and print styles
static/js/main.js   form helpers, live scoring, copy link, confirmations
schema.sql          MySQL database and user setup
```
