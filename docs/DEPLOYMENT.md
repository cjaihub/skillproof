# Deployment

SkillProof is a standard WSGI app: `app:app` (module `app.py`, object `app`). It serves its own HTML, CSS and JS.

## Configuration

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | **yes** (prod) | Signs sessions and tokens. All workers must share it. |
| `DATABASE_URL` | yes (prod) | `mysql+pymysql://user:pass@host:3306/skillproof?charset=utf8mb4`. Without it, SQLite is used. |
| `UPLOAD_FOLDER` | recommended | Persistent, private directory for evidence and imports |
| `SESSION_COOKIE_SECURE` | yes (prod) | `1` behind HTTPS |
| `FLASK_DEBUG` | no | `0` in production |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `MAIL_FROM` | recommended | Email confirmation and password reset |
| `SHOW_DEV_LINKS` | no | `0` hides the on-screen email links shown when there's no SMTP |
| `ANTHROPIC_API_KEY` | optional | Turns on AI features ([AI.md](AI.md)) |
| `SKILLPROOF_AI_MODEL`, `SKILLPROOF_AI` | optional | Model choice; `off` forces fallbacks |
| `PORT` | platform | Port for `python app.py` (default 5050) |

## MySQL

```bash
mysql -u root -p < schema.sql
```
This creates the `skillproof` database (`utf8mb4`) and its user. Change the password in `schema.sql` first. Tables are
created on first start. MySQL 8's default authentication needs `pip install cryptography`.

## Run with Gunicorn

```bash
gunicorn -w 3 -k gthread --threads 4 --timeout 120 -b 0.0.0.0:$PORT app:app
```
Threads let the streaming assistant (SSE) run without blocking other requests. If you use nginx in front, keep buffering off
for `/api/assistant` (the app already sends `X-Accel-Buffering: no`).

## Platforms

| Platform | Notes |
|---|---|
| **Render** | Web Service. Build: `pip install -r requirements.txt`. Start: the gunicorn command above. Add a persistent disk for `UPLOAD_FOLDER`, and MySQL from Aiven or Railway. |
| **Railway** | Add a MySQL plugin; set `DATABASE_URL` from its variables (switch the scheme to `mysql+pymysql://`). Add a volume for uploads. |
| **Fly.io** | `fly launch`, then a volume mounted at the `UPLOAD_FOLDER` path; set secrets with `fly secrets set`. |
| **PythonAnywhere** | WSGI file imports `from app import app as application`; MySQL is included on paid plans. |
| **Netlify** | Static only, so it **can't run Flask**. Use it for a landing page that links to the app. |

## Database changes

There are no migrations yet. `db.create_all()` creates missing tables but does **not** change existing ones. For production
schema changes, add [Flask-Migrate](https://flask-migrate.readthedocs.io/) (Alembic) before going live.

## After deploying

1. Create the first admin account: register, then set `role='admin'` and `status='active'` directly in the database.
2. Sign in, approve assessors and employers, and check **Admin → Settings**.
3. Run the [security checklist](SECURITY.md#production-checklist).
