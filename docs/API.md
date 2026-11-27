# Routes & API

SkillProof is mostly server-rendered HTML. Every `POST` needs a CSRF token: the form field `csrf`, or the
`X-CSRF-Token` header for JSON calls. The token is available in templates as `csrf_token`.

Access legend: **public** · **any** (signed in) · **C** candidate · **A** assessor · **E** employer · **Adm** admin.

## Public & account

| Method | Path | Access | Purpose |
|---|---|---|---|
| GET | `/` | public | Landing page with "how it works" wizard |
| GET | `/privacy` | public | Privacy notice |
| GET | `/p/<token>` | public | Shared competency report (only while consent is on). `?area=<category>` shows one competence area |
| GET, POST | `/register` | public | 3-step registration wizard |
| GET, POST | `/login` | public | Sign in (lockout after 5 failures) |
| POST | `/logout` | any | Sign out |
| GET | `/verify/<token>` | public | Confirm email |
| POST | `/verify/resend` | any | Resend confirmation |
| GET, POST | `/forgot` | public | Request password reset |
| GET, POST | `/reset/<token>` | public | Set new password (single use, expires) |
| GET | `/pending` | any | "Awaiting approval" screen |
| GET | `/dashboard` | any | Role-specific dashboard |
| GET | `/notifications` | any | Notification list |
| GET | `/n/<id>` | any | Open a notification (marks read, then redirects) |
| POST | `/notifications/read` | any | Mark all read |
| GET | `/account` | any | Account settings and sign-in history |
| POST | `/account/profile` · `/account/password` | any | Update name and contact details · change password (signs out other devices) |
| GET | `/account/export` | any | Download all my data (JSON) |
| POST | `/account/delete` | any | Delete account and files |

## Candidate

| Method | Path | Purpose |
|---|---|---|
| GET, POST | `/profile` | Headline, location, summary |
| POST | `/experience` · `/experience/<id>/delete` | Add or remove work history |
| GET | `/skills` | Skills list |
| GET, POST | `/skills/new` · `/skills/<id>/edit` | Create or edit a skill |
| GET | `/skills/<id>` | Skill detail: status, practical task, test, assessments |
| POST | `/skills/<id>/delete` | Delete a skill |
| GET, POST | `/skills/<id>/test` | Take the online skills test |
| POST | `/skills/<id>/request` | Submit for assessment (needs a submitted test and a task answer) |
| GET, POST | `/evidence` | List and upload evidence |
| GET | `/evidence/<id>/file` | Download a file (owner, assessors, admins only) |
| POST | `/evidence/<id>/delete` | Delete evidence |
| GET, POST | `/import` | Upload a document for AI import |
| GET | `/import/<id>` | Review suggestions |
| POST | `/import/<id>/apply` · `/import/<id>/discard` | Keep the ticked suggestions · discard |
| GET | `/report` | Competency report (`?area=`) |
| POST | `/consent` | Turn sharing on or off, or rotate the link |
| POST | `/assessments/<id>/appeal` | Appeal a decision |
| GET | `/my-access-log` | Who viewed my data |
| GET, POST | `/job-access` | Job-readiness checklist and request |
| GET | `/jobs` | Job board sorted by match |
| GET, POST | `/jobs/<id>` | Job detail and apply |
| GET | `/my-applications` | Application tracker |
| POST | `/applications/<id>/withdraw` | Withdraw an application |

## Assessor

| Method | Path | Purpose |
|---|---|---|
| GET | `/review` | Queue with SLA flags and category filter |
| GET, POST | `/review/<skill_id>` | Review evidence, test and task; score the 4 criteria |
| POST | `/review/<skill_id>/ai` | Ask for an AI evidence review (advisory) |

## Employer

| Method | Path | Purpose |
|---|---|---|
| GET | `/employer` | Hiring dashboard |
| GET | `/talent` | Talent search (`q`, `category`, `location`, `level`, `verified`, `sort`) |
| GET | `/talent/<uid>` | Candidate report (logged in the candidate's access log) |
| POST | `/shortlist/<uid>` | Add or remove from the shortlist, with a note |
| GET | `/employer/jobs` | My jobs |
| GET, POST | `/employer/jobs/new` · `/employer/jobs/<id>/edit` | Post or edit a job (goes back to admin approval) |
| GET | `/employer/jobs/<id>` | Applicants with match scores |
| POST | `/employer/jobs/<id>/close` | Close a job |
| POST | `/applications/<id>/status` | Move an applicant through the pipeline |

## Admin

| Method | Path | Purpose |
|---|---|---|
| GET | `/admin` | KPIs, trends, charts, live activity |
| GET | `/admin/users` · `/admin/users.csv` | Search and filter users · CSV export |
| GET | `/admin/users/<id>` | User detail |
| POST | `/admin/users/<id>/action` | approve, reject, suspend, reactivate, verify identity, change role, sign out everywhere |
| POST | `/admin/users/bulk` | Bulk approve, suspend or reactivate |
| POST | `/admin/users/<id>/job-access` | Grant or decline job access |
| GET | `/admin/verifications` | Pending accounts, identity checks, job-access requests |
| GET | `/admin/assessments` | All assessments |
| GET | `/admin/appeals` · POST `/admin/appeals/<id>` | Appeals and their resolution |
| GET | `/admin/jobs` · POST `/admin/jobs/<id>/review` | Approve or reject job ads |
| GET | `/admin/audit` | Audit log |
| GET, POST | `/admin/settings` | Platform switches |

---

## JSON APIs

### `POST /api/assistant`: onboarding chat (Server-Sent Events)

Request:
```json
{
  "messages": [{"role": "user", "content": "How do I add evidence if I lost my certificate?"}],
  "page": "/skills/3"
}
```
- At most 12 turns are kept, 1,500 characters per message. The history must end with a `user` message.
- Rate limit: 20 messages per 10 minutes per session, which returns `429 {"error": "..."}`.

The response is `text/event-stream`. Each event is `data: <json>`:
```
data: {"mode": "ai"}            ← or "guide" when no API key / API unreachable
data: {"t": "First, open "}     ← text chunks, appended in order
data: {"t": "Evidence…"}
data: {"done": true}
```

### `POST /api/translate`: translate user-written content

Request (header `X-CSRF-Token`):
```json
{ "lang": "sw", "texts": ["I worked as a nurse for 6 years in Juba.", "..."] }
```
- Up to 40 texts per call, each cut to 4,000 characters. `lang` must be one of the 13 language codes.
- Rate limit: 30 requests per 10 minutes per session.

Responses:
| Status | Body |
|---|---|
| 200 | `{"translations": ["...", "..."]}` in the same order as `texts` |
| 400 | `{"error": "bad request"}` |
| 429 | `{"error": "<translated message>"}` |
| 503 | `{"error": "<translated message>"}` when AI is unavailable and the text is not in the cache |

Translations are cached in `content_translations` by SHA-256 of the source text and language, so each text is only translated once.
