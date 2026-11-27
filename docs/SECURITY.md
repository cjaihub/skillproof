# Security & privacy

SkillProof holds sensitive data about vulnerable people: displacement history, nationality hints and work records.
It is designed around the **Kenya Data Protection Act, 2019** and the principle of collecting as little as possible.

## Threat model (summary)

| Threat | Control |
|---|---|
| Credential stuffing / brute force | Lockout after 5 failed logins; password rules (8+ characters, letters and numbers, not containing the email, not a common password); generic error messages |
| Session theft or a stale session | HttpOnly, SameSite=Lax cookies; `Secure` in production; `session_version` revokes all sessions on password change, suspension or "sign out everywhere" |
| CSRF | Per-session token on every POST (form field or `X-CSRF-Token` header) |
| Open redirect after login | `next` accepted only when it's a local path |
| Clickjacking, MIME sniffing | `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, strict `Referrer-Policy` |
| Fake employers and job scams | Employers need admin approval; every job ad is approved before it is published; scam warning on job pages |
| Unqualified or biased assessors | Assessors are vetted; published criteria; written feedback required; no self-assessment; conflict-of-interest confirmation; upheld appeals go to someone else |
| Leaked evidence files | Stored outside `static/`, random filenames, permission check per download; **employers never get files** |
| Malicious uploads | Extension allow-list, 10 MB limit, files never executed or served inline as HTML |
| Over-collection | Users told not to upload ID or refugee numbers; AI import refuses identity documents |
| AI misuse / prompt injection | AI output is advisory and typed (Pydantic); assistant links restricted to SkillProof paths; rate limits; refusals handled |
| Insider misuse | Audit log for assessments, role, status, consent and identity changes, and profile and evidence views; candidates can see who viewed their data |

## Data subject rights

| Right | Feature |
|---|---|
| Access / portability | **Download my data** (JSON) at `/account/export` |
| Transparency | **Who viewed my data** at `/my-access-log` |
| Consent | Sharing is off by default, needs explicit consent (timestamped), can be withdrawn; the link can be rotated |
| Rectification | Edit profile and skills; appeal assessments |
| Erasure | **Delete my account** removes the profile, skills, evidence files, imports, applications and jobs |

## Passwords and tokens

- Werkzeug `generate_password_hash` (salted scrypt or pbkdf2).
- Email-verification and reset tokens are signed with `itsdangerous`, expire, and reset links work only once (they are tied to the current password hash).
- `SECRET_KEY` comes from the environment, or is generated once into `.secret_key` (git-ignored).

## Production checklist

- [ ] Set a strong `SECRET_KEY` (`python -c "import secrets; print(secrets.token_hex(32))"`)
- [ ] Serve over HTTPS and set `SESSION_COOKIE_SECURE=1`
- [ ] `FLASK_DEBUG=0`, `SHOW_DEV_LINKS=0`, and configure SMTP
- [ ] Remove demo accounts (do not run `seed.py` in production)
- [ ] Put evidence in encrypted object storage with private access
- [ ] Add IP-based rate limiting at the proxy (for example nginx `limit_req`)
- [ ] Back up the database daily, encrypted
- [ ] Register with the **ODPC** as data controller/processor and carry out a **DPIA**
- [ ] Have the privacy notice reviewed by a lawyer; agree data-sharing terms with partner organisations
- [ ] Review machine-drafted translations of legal and consent text with native speakers

## Reporting a vulnerability

Please do not open a public issue. Contact the maintainer privately through GitHub, with steps to reproduce.
