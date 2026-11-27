# Contributing

Thanks for helping people prove their skills.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python seed.py --reset && python app.py
```

## Before a pull request

```bash
python test_flow.py && python test_links.py
```
Both must pass. Add checks to `test_flow.py` for new behaviour.

## Conventions

- **Routes** go in the matching `views/<area>.py` inside `register(app)`. Protect them with `@login_required("role", ...)`.
- **Mutations** that matter for accountability call `core.log(action, subject, detail)`; tell users with `core.notify(...)`.
- **Every user-facing string** goes through `_()`: in templates `{{ _('Text') }}`, in Python `from i18n import gettext as _`.
  Run `python tools/wrap_strings.py templates/<file>.html` on new templates. Wrap user-written content in `<span data-tr>`.
- **No new frontend dependencies.** Use the CSS tokens and components in `style.css`; charts go through `data-chart`.
- **AI features** must return a Pydantic model through `ai._parse`, catch `AIUnavailable`, and have a non-AI fallback.
- **Privacy first.** Don't collect new personal data without a clear need, and never show evidence files to employers.
- Schema changes: note them in the PR; reviewers need to run `python seed.py --reset`.

## Translations

Native speakers are the most valuable contributors. Pick a `translations/<code>.json`, fix or confirm strings, and
remove the keys you reviewed from `translations/<code>.machine.json`. See [docs/I18N.md](docs/I18N.md).
