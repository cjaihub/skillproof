"""Mark plain English text in Jinja templates for translation by wrapping it in {{ _("...") }}.

Handles text between tags, common text attributes (placeholder, title, aria-label, data-confirm,
data-busy, alt) and string literals passed to the kpi()/empty()/act() macros. Jinja tags are
shielded before any HTML parsing, and text already inside {{ }} or {% %} is left alone, so the
script is safe to run repeatedly.

    python tools/wrap_strings.py templates/            # rewrite in place
    python tools/wrap_strings.py templates/ --dry-run  # show counts only
"""
import html
import re
import sys
from pathlib import Path

LETTERS = re.compile(r"[A-Za-z]{2,}")
JINJA = re.compile(r"\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}", re.S)
SKIP_BLOCKS = re.compile(r"(<script\b.*?</script>|<style\b.*?</style>|<code\b.*?</code>|<svg\b.*?</svg>|<head>.*?</head>)",
                         re.S | re.I)
ATTRS = re.compile(r'\b(placeholder|title|aria-label|data-confirm|data-busy|alt)="([^"]*)"')
IDENT = re.compile(r"^[a-z0-9]+([-_][a-z0-9]+)+$")
KEEP = {"SkillProof", "Python", "SQL", "React", "PDF", "CSV", "JSON", "AI", "EN", "UTC", "IP", "KES", "Cisco IOS", "beta",
        "Python / Flask", "Amina H.", "Jean-Pierre H.", "Amina Hassan", "Nairobi", "Kakuma", "Python, SQL, REST APIs"}


def q(text):
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def translatable(core):
    return (core and LETTERS.search(core) and core not in KEEP and not IDENT.match(core)
            and not re.match(r"^[A-Z]{1,3}$", core) and "@" not in core and "://" not in core
            and not core.startswith(("http", "/", "#", "Ref ", "skillproof.org")) and "\x00" not in core)


def wrap_text_piece(piece):
    core = piece.strip()
    # keep separators like "· " outside the translated text
    m = re.match(r"^([·•|:,–\-\s]*)(.*?)([·•|:,–\-\s]*)$", core, re.S)
    pre, word, post = m.group(1), m.group(2), m.group(3)
    if not translatable(word):
        return piece
    lead = piece[: len(piece) - len(piece.lstrip())]
    trail = piece[len(piece.rstrip()):]
    text = " ".join(html.unescape(word).split())
    return f"{lead}{pre}{{{{ _({q(text)}) }}}}{post}{trail}"


def wrap_macro_call(tag):
    """{{ kpi('Label', value, 'icon', 'Sub text') }} -> wrap human-readable string literals."""
    m = re.match(r"(\{\{-?\s*)(kpi|empty|act)\((.*)\)(\s*-?\}\})$", tag, re.S)
    if not m:
        return tag
    args = m.group(3)

    def rep(lit):
        val = lit.group(1) if lit.group(1) is not None else lit.group(2)
        before = args[:lit.start()].rstrip()
        if before.endswith("_(") or not translatable(val) or (" " not in val and val == val.lower()):
            return lit.group(0)
        return f"_({q(val)})"
    new_args = re.sub(r"'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\"", rep, args)
    return f"{m.group(1)}{m.group(2)}({new_args}){m.group(4)}"


def process(src):
    out = []
    for i, chunk in enumerate(SKIP_BLOCKS.split(src)):
        if i % 2 == 1:
            out.append(chunk)
            continue
        # 1. shield Jinja so '<' / '>' inside expressions can't confuse the HTML split
        tags = []

        def shield(m):
            tags.append(wrap_macro_call(m.group(0)))
            return f"\x00{len(tags) - 1}\x00"
        body = JINJA.sub(shield, chunk)
        # 2. wrap text nodes and text attributes
        pieces = re.split(r"(<[^>]*>)", body)
        for j, p in enumerate(pieces):
            if j % 2 == 0:
                pieces[j] = "".join(wrap_text_piece(s) if not re.fullmatch(r"\x00\d+\x00", s) else s
                                    for s in re.split(r"(\x00\d+\x00)", p))
            else:
                pieces[j] = ATTRS.sub(lambda a: (f'{a.group(1)}="{{{{ _({q(html.unescape(a.group(2)))}) }}}}"'
                                                 if translatable(a.group(2).strip()) else a.group(0)), p)
        body = "".join(pieces)
        # 3. restore Jinja
        out.append(re.sub(r"\x00(\d+)\x00", lambda m: tags[int(m.group(1))], body))
    return "".join(out)


if __name__ == "__main__":
    root = Path(sys.argv[1])
    dry = "--dry-run" in sys.argv
    total = 0
    for path in sorted(root.rglob("*.html")):
        if path.name == "_icons.html":
            continue
        src = path.read_text(encoding="utf-8")
        new = process(src)
        n = new.count("_(") - src.count("_(")
        if n:
            total += n
            print(f"{path}: {n}")
            if not dry:
                path.write_text(new, encoding="utf-8")
    print(f"{total} strings wrapped")
