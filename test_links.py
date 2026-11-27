"""Crawl every page as every role and follow every link: nothing may error or dead-end.
Run: python test_links.py"""
import os
import re
import tempfile
from html import unescape
from urllib.parse import urlsplit

tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/links.db"
os.environ["UPLOAD_FOLDER"] = f"{tmp}/uploads"
os.environ["SKILLPROOF_AI"] = "off"

from app import app  # noqa: E402
import seed  # noqa: E402

seed.run(reset=True)
SKIP = ("/logout", "/account/export", "/admin/users.csv", "/static/", "/evidence/")  # side effects or downloads
ROLES = [None, "amina@skillproof.test", "yusuf@skillproof.test", "nyaruach@skillproof.test", "assessor@skillproof.test",
         "employer@skillproof.test", "admin@skillproof.test", "hiring@greenbuild.test"]
problems = []
total = 0


def login(c, email):
    html = c.get("/login").get_data(as_text=True)
    tok = re.search(r'name="csrf" value="([^"]+)"', html).group(1)
    c.post("/login", data={"email": email, "password": seed.DEMO_PASSWORD, "csrf": tok})


for who in ROLES:
    c = app.test_client()
    if who:
        login(c, who)
    seen, queue = set(), ["/", "/dashboard" if who else "/login", "/notifications" if who else "/register"]
    while queue and len(seen) < 1500:
        url = queue.pop(0)
        path = urlsplit(url).path
        if url in seen or any(path.startswith(s) for s in SKIP) or "lang=" in url:
            continue
        seen.add(url)
        r = c.get(url)
        total += 1
        if r.status_code >= 500 or r.status_code == 404 and not url.startswith("/p/"):
            problems.append(f"{who or 'visitor'}: {url} -> {r.status_code}")
            continue
        if r.status_code in (301, 302):
            loc = r.location
            if path.startswith("/n/") and "/notifications" in loc:
                problems.append(f"{who}: notification {url} leads back to the list")
            if loc.startswith("/") or loc.startswith("http://localhost/"):
                queue.append(loc.replace("http://localhost", ""))
            continue
        if "text/html" not in r.content_type:
            continue
        for href in re.findall(r'href="([^"]+)"', r.get_data(as_text=True)):
            href = unescape(href)
            if href.startswith("/") and not href.startswith("//") and "#" not in href[:1]:
                href = href.split("#")[0]
                if href and href not in seen:
                    queue.append(href)
            elif href in ("#", "", "javascript:void(0)"):
                problems.append(f"{who or 'visitor'}: dead link href='{href}' on {url}")
    print(f"{who or 'visitor':<28} {len(seen):>4} pages and links checked")

print(f"\n{total} requests made")
if problems:
    print(f"{len(problems)} problems:")
    print("\n".join(sorted(set(problems))))
    raise SystemExit(1)
print("No broken or dead links.")
