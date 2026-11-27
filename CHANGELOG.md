# Changelog

All notable changes to SkillProof. Dates are in UTC.

## [1.0.0] - 2026-11-27

The first complete prototype, ready for a pilot.

### Platform
- Four roles with their own workspaces: candidates, assessors, employers and admins.
- Registration wizard, email confirmation, login lockout, password reset, sign-in history and "sign out everywhere".
- Admin approval for employers and assessors; identity verification; bulk user actions and CSV export.

### Skills and assessment
- Skills profile, work history and private evidence (files or links).
- Two-stage assessment: auto-marked online skills test, then a practical task scored by an assessor on 4 published criteria.
- Pass rule: 12/20 or more, with no criterion below 2. Appeals go to a different assessor.
- Premium competency report grouped into competence areas, shareable in full or per area, with consent and revocable links.

### Jobs
- Job access granted by admins to verified candidates.
- Admin-approved job ads, skills-match scores, and an applicant pipeline from Applied to Hired.

### AI (optional, with non-AI fallbacks)
- Document import that suggests skills, history and corrections.
- AI-written skills tests, advisory evidence review for assessors, an onboarding assistant, and translation of user-written content.

### Languages and design
- 13 interface languages, including right-to-left Arabic and eight local languages (machine drafts flagged for review).
- Light, dark and system themes; responsive from phone to desktop; print styles.

### Engineering
- 248 end-to-end checks, a link crawler, ruff linting and GitHub Actions CI on Python 3.11 to 3.13.
- Full documentation in `docs/`.
