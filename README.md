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

> **Upgrading from an earlier version?** The database schema changed. Run `python seed.py --reset`
> (local SQLite), or drop and recreate the MySQL database.

### Languages
| Coverage | Languages |
|---|---|
| Most screens (~87%) | English, Kiswahili, Français, العربية (right-to-left), Soomaali |
| Core screens (navigation, home, sign-in, assistant); rest falls back to English, marked **beta** | Kinyarwanda, Ikirundi, አማርኛ (Amharic), ትግርኛ (Tigrinya), Afaan Oromoo, Lingála, Dholuo, Gĩkũyũ |

The globe button switches language; the choice is remembered, and first-time visitors get their browser's
language. The assistant also replies in whatever language a user writes in (including Turkana, Nuer or Dinka).
Templates use `{{ _('English text') }}`; each language has `translations/<code>.json`.
```bash
python i18n.py                    # coverage report per language
```
```bash
python i18n.py --translate rw     # draft missing strings with Claude (needs ANTHROPIC_API_KEY); 'all' for every language
```
To add a language, add it to `LANGUAGES` in `i18n.py` and run the translate command. **All translations are drafts:
have native speakers review them before launch** (especially the local languages).

### AI document import ("Import with AI")
Candidates upload a CV, certificate, reference letter or photo of their work (PDF, Word, JPG/PNG, text). Claude reads
it and returns structured suggestions: skills with an estimated level, work history, headline and summary, plus
**corrections** where the profile disagrees with the document. Nothing is saved until the candidate ticks what to keep;
the file can be kept as private evidence. Identity documents are detected and refused. Without an API key, a basic
reader extracts text from PDF/Word/text and matches skills and dates.

### Skills test, then practical task
Requesting assessment is now two steps: an **online skills test** (6 multiple-choice questions written by Claude
for that specific skill and level, or from a built-in question bank per category, plus 2 written answers, auto-marked,
answers kept server-side) and the **practical task**. Assessors see the test results, and can ask for an
**AI evidence review**: Claude reads the evidence files, test answers and task, suggests a score per criterion with
reasons, and lists strengths, concerns, things to check and questions to ask. It is advisory: the assessor copies the
scores only if they agree, and still writes their own feedback.

### Job access and jobs
1. A candidate with a verified skill, a confirmed email, a 70%+ profile and sharing on **requests job access**.
2. An **admin grants or declines** it (Verifications page, or the user's page), with a note.
3. **Employers post jobs**, which wait for **admin approval** (to block scams); approved jobs notify job-ready candidates with a 60%+ match.
4. Candidates see jobs sorted by **skills match** (verified skills count fully, self-declared partly) and apply with a note.
5. Employers move applicants through Applied → Shortlisted → Interview → Offer → Hired; candidates track this in *My applications*.

### Competence areas in the report
Skills are grouped into **competence areas** (one per category). The report shows each area's assessed level,
average scores per criterion and skill scorecards. A candidate can share the **full report or one competence**
(`/p/<link>?area=Healthcare`), for example a teaching report for a school and a software report for a tech company.

### Appearance
Light, Dark or **System** (default: follows the device and switches live). Picker in the header; on phones it's in the user menu.

### AI onboarding assistant
The "Need help?" button opens a chat that guides people through registering, building a profile, adding evidence
when certificates are lost, getting assessed and sharing a report, in the page's language, and with the user's own
next step. It streams answers from **Claude** (`claude-opus-5-5`, low effort for quick replies) with server-side
refusal fallback enabled.
- **To turn on AI answers**, set `ANTHROPIC_API_KEY` in `.env` (from console.anthropic.com). Without a key, or if the
  API is unreachable, it uses a built-in **guide mode** with translated answers, so the demo always works.
- Optional: `SKILLPROOF_AI_MODEL` to choose another model; `SKILLPROOF_AI=off` to force guide mode.
- **Privacy:** only the user's role, onboarding progress, current page and language are sent as context, never their
  name, email or files. Chats aren't stored by SkillProof. Users are told not to share passwords or ID numbers.
- **Safety:** 20 messages per 10 minutes per session, CSRF-protected, history limited to 12 turns and 1,500 characters
  per message, links restricted to SkillProof pages, and legal, asylum and health questions referred to UNHCR or support organisations.

### Demo accounts (after `python seed.py`)
All use the `DEMO_PASSWORD` in [seed.py](seed.py). The login page has one-click demo buttons in development. **Demo only: remove before real use.**

| Role | Email | What to try |
|---|---|---|
| Admin | `admin@skillproof.test` | Platform dashboard, approve 2 pending accounts, verify identities, appeals, settings |
| Candidate | `amina@skillproof.test` | Identity-verified, 2 assessed skills, shared report, profile-view chart |
| Candidate | `nyaruach@skillproof.test` | Not-verified skill with an open appeal |
| Assessor | `assessor@skillproof.test` | Assessment queue with SLA tracking, scoring form |
| Assessor | `assessor2@skillproof.test` | Second assessor (blocked from reassessing after an upheld appeal) |
| Employer | `employer@skillproof.test` | Hiring dashboard, talent search, shortlist with notes |
| Employer (pending) | `hiring@greenbuild.test` | Sees the "awaiting approval" screen until an admin approves |

### 5-minute demo script
1. **Register** with the 3-step wizard (role → details → password strength meter + consent). Employers and assessors land on *Awaiting approval*.
2. Without an email server, confirmation and reset links appear on screen (yellow notice), so you can click through the flow.
3. As **admin** → *Verifications* → approve the employer; open a user → verify identity, suspend, change role, sign out everywhere.
4. As a **candidate** → add a skill → evidence → practical task → *Submit for assessment*.
5. As **assessor** → *Assessment queue* → score 4 criteria (live pass/fail) → confirm no conflict of interest → save. The candidate gets a notification.
6. As **candidate** → *Competency report* → consent → share link. As **employer** → *Find talent* → filter → shortlist and add a note.
7. As **admin** → *Appeals* → uphold → the skill returns to the queue for a *different* assessor. The *Dashboard* shows the success indicators.

---

## How it maps to the proposal

| Proposal feature | Where |
|---|---|
| User registration | `/register`: 3-step wizard for candidates, employers and assessor applicants; email confirmation; employers and assessors need admin approval |
| Secure login | Show/hide password, *keep me signed in*, lockout after 5 failed attempts, forgot/reset password by email, sign-in history |
| Skills profile | `/profile` (headline, summary, work history) and `/skills/new` (skill, category, level, years) |
| Evidence submission | `/evidence`: files (PDF/image/Word/zip, 10 MB) or links, linked to a skill |
| Skills assessment | Practical task per category → assessor scores 4 published criteria (0–5). Pass = 12/20 with no criterion below 2 |
| Verification dashboard | `/review`: assessor workspace with KPIs, SLA flags, category filter, decision charts |
| Admin management | `/admin` dashboard (KPIs with week-over-week trends, growth chart, funnel, workload, live activity), `/admin/users` (search, filter, bulk actions, CSV export), `/admin/verifications`, `/admin/assessments`, `/admin/appeals`, `/admin/audit`, `/admin/settings` |
| Digital competency report | `/report`: printable / save-as-PDF, with assessment references |
| Employer access | `/employer` hiring dashboard and `/talent` search (keyword, category, location, level, verified-only, sort) with shortlist and private notes |
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

- **Account security**: email confirmation, lockout after 5 failed logins, single-use expiring reset links,
  password change/reset signs out other devices, admin can suspend or force sign-out, security headers.
- **Vetted employers and assessors**: approved by an admin before they can see candidates or assess.

Before a real launch: register with the ODPC as a data controller/processor, do a Data Protection Impact
Assessment, use HTTPS (`SESSION_COOKIE_SECURE=1`), configure SMTP, put uploads in encrypted object storage,
add IP-based rate limiting, and have the privacy notice reviewed by a lawyer.

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
app.py                 application factory, session/CSRF/approval gate, template helpers
core.py                access control, audit, notifications, tokens, email, settings, chart data
models.py              database models, criteria, statuses
views/                 routes per area: public, auth, candidate, assessor, employer, admin
templates/layouts/     public site, split-screen auth, sidebar app shell
templates/<role>/      pages for each role
static/css/style.css   design system: light/dark themes, responsive layout, print styles
static/js/main.js      theme, wizard, password meter, bulk select, live scoring, toasts
static/js/charts.js    dependency-free SVG line/bar/donut charts
seed.py · test_flow.py demo data · end-to-end test (python test_flow.py)
```
