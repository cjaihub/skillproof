"""End-to-end test of the SkillProof flow. Run: python test_flow.py"""
import io
import os
import re
import tempfile

tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/test.db"
os.environ["UPLOAD_FOLDER"] = f"{tmp}/uploads"

from app import app  # noqa: E402
import seed  # noqa: E402
from models import Skill, User, db  # noqa: E402

seed.run(reset=True)
PW = seed.DEMO_PASSWORD


def client():
    return app.test_client()


def csrf(c, path="/login"):
    html = c.get(path).get_data(as_text=True)
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


def login(c, email):
    r = c.post("/login", data={"email": email, "password": PW, "csrf": csrf(c)})
    assert r.status_code == 302, r.status_code
    return c


def post(c, path, data, page="/dashboard", **kw):
    data = {"csrf": csrf(c, page), **data}
    return c.post(path, data=data, **kw)


ok = 0
def check(cond, msg):
    global ok
    assert cond, msg
    ok += 1
    print("  ✓", msg)


# Every page renders for every role
pages = {
    None: ["/", "/privacy", "/login", "/register", "/register?role=employer"],
    "amina@skillproof.test": ["/dashboard", "/profile", "/evidence", "/report", "/account", "/my-access-log", "/skills/new"],
    "assessor@skillproof.test": ["/review", "/account"],
    "employer@skillproof.test": ["/talent", "/talent?q=python&searched=1&verified=1", "/talent?searched=1"],
    "admin@skillproof.test": ["/admin", "/admin/appeals", "/admin/audit", "/review", "/talent"],
}
for who, paths in pages.items():
    c = client()
    if who:
        login(c, who)
    for p in paths:
        r = c.get(p)
        check(r.status_code == 200, f"{who or 'anon'} GET {p}")

# CSRF protection
c = client()
check(c.post("/login", data={"email": "x", "password": "y"}).status_code == 400, "POST without CSRF token rejected")

# 1. Register a new candidate
c = client()
r = c.post("/register", data={"csrf": csrf(c, "/register"), "role": "candidate", "full_name": "Test Refugee",
                               "email": "test@example.org", "password": "longpassword1", "confirm": "longpassword1",
                               "agree": "1"})
check(r.status_code == 302 and "/dashboard" in r.location, "candidate registers")
with app.app_context():
    u = User.query.filter_by(email="test@example.org").one()
    check(u.password_hash != "longpassword1" and u.password_hash.startswith(("scrypt", "pbkdf2")), "password is hashed")
    check(not u.consent_share, "sharing is off by default")
    uid, token = u.id, u.share_token

check(c.get(f"/p/{token}").status_code == 404, "share link hidden without consent")
check(c.get("/review").status_code == 403, "candidate cannot open assessor queue")
check(c.get("/admin").status_code == 403, "candidate cannot open admin")

# 2. Profile, experience, skill
post(c, "/profile", {"full_name": "Test Refugee", "headline": "Electrician", "location": "Kakuma", "bio": "10 years wiring."}, "/profile")
post(c, "/experience", {"title": "Electrician", "start_year": "2012", "end_year": "2022"}, "/profile")
r = post(c, "/skills/new", {"name": "Electrical installation", "category": "Trades & vocational", "claimed_level": "4", "years": "10"}, "/skills/new")
sid = int(r.location.rsplit("/", 1)[-1])
check("Self-declared" in c.get("/report").get_data(as_text=True), "new skill shows as self-declared")

# 3. Evidence upload + access control
r = post(c, "/evidence", {"title": "Wiring photo", "kind": "work_sample", "skill_id": str(sid),
                          "file": (io.BytesIO(b"%PDF-1.4 test"), "wiring.pdf")}, "/evidence",
         content_type="multipart/form-data")
check(r.status_code == 302, "evidence uploaded")
bad = post(c, "/evidence", {"title": "x", "file": (io.BytesIO(b"x"), "evil.exe")}, "/evidence", content_type="multipart/form-data")
with app.app_context():
    ev = Skill.query.get(sid).evidence
    check(len(ev) == 1 and ev[0].stored_name.endswith(".pdf") and ev[0].stored_name != "wiring.pdf", "file stored under random name; .exe rejected")
    eid = ev[0].id
check(c.get(f"/evidence/{eid}/file").status_code == 200, "owner can download evidence")
emp = login(client(), "employer@skillproof.test")
check(emp.get(f"/evidence/{eid}/file").status_code == 403, "employer cannot download evidence")
other = login(client(), "jean@skillproof.test")
check(other.get(f"/evidence/{eid}/file").status_code == 403, "another candidate cannot download evidence")
check(c.get("/static/../uploads").status_code == 404, "uploads not under static")

# 4. Request assessment
r = post(c, f"/skills/{sid}/request", {"task_response": "short"}, f"/skills/{sid}")
with app.app_context():
    check(Skill.query.get(sid).status == "self_declared", "too-short task response refused")
post(c, f"/skills/{sid}/request", {"task_response": "I installed a three-phase distribution board, isolating supply, testing with a multimeter " * 2}, f"/skills/{sid}")
with app.app_context():
    check(Skill.query.get(sid).status == "pending", "assessment requested")

# 5. Assessor fails it
a = login(client(), "assessor@skillproof.test")
check("Electrical installation" in a.get("/review").get_data(as_text=True), "skill appears in assessor queue")
check(a.get(f"/evidence/{eid}/file").status_code == 200, "assessor can open evidence")
scores = {"score_knowledge": "3", "score_practical": "1", "score_evidence": "3", "score_communication": "3"}
post(a, f"/review/{sid}", {**scores, "comments": "too short"}, f"/review/{sid}")
with app.app_context():
    check(Skill.query.get(sid).status == "pending", "assessment needs written feedback")
post(a, f"/review/{sid}", {**scores, "assessed_level": "3",
                           "comments": "Practical answer lacks safety steps such as lock-out/tag-out."}, f"/review/{sid}")
with app.app_context():
    s = Skill.query.get(sid)
    check(s.status == "not_verified", "low criterion (1) fails despite 10/20 total")
    aid = s.latest_assessment.id

# 6. Appeal -> admin upholds -> original assessor blocked -> second assessor verifies
post(c, f"/assessments/{aid}/appeal", {"reason": "The safety steps were in my uploaded photo notes, please re-check."}, f"/skills/{sid}")
adm = login(client(), "admin@skillproof.test")
with app.app_context():
    from models import Appeal
    apid = Appeal.query.filter_by(user_id=uid).one().id
post(adm, f"/admin/appeals/{apid}", {"decision": "upheld", "resolution": "Evidence notes were not considered."}, "/admin/appeals")
with app.app_context():
    check(Skill.query.get(sid).status == "pending", "upheld appeal returns skill to queue")
r = a.get(f"/review/{sid}")
check(r.status_code == 302, "original assessor blocked from reassessing")
a2 = login(client(), "assessor2@skillproof.test")
post(a2, f"/review/{sid}", {"score_knowledge": "4", "score_practical": "4", "score_evidence": "3", "score_communication": "4",
                            "assessed_level": "4", "comments": "Photos and notes show correct isolation and testing procedure."}, f"/review/{sid}")
with app.app_context():
    check(Skill.query.get(sid).status == "verified", "second assessor verifies (15/20)")

# 7. Consent & employer access
check("Test Refugee" not in emp.get("/talent").get_data(as_text=True), "employer can't find candidate before consent")
check(emp.get(f"/talent/{uid}").status_code == 404, "employer can't open profile before consent")
post(c, "/consent", {"share": "1"}, "/report")
check("Test Refugee" in emp.get("/talent?q=Electrical&searched=1&verified=1").get_data(as_text=True), "employer finds candidate after consent")
page = emp.get(f"/talent/{uid}").get_data(as_text=True)
check("Independently assessed" in page and "wiring.pdf" not in page and "test@example.org" not in page,
      "employer sees assessed skills but not files or email")
check(client().get(f"/p/{token}").status_code == 200, "public link works after consent")
check("profile view employer" in c.get("/my-access-log").get_data(as_text=True), "candidate sees employer view in access log")
post(c, "/consent", {"share": "0"}, "/report")
check(client().get(f"/p/{token}").status_code == 404, "link stops working when consent withdrawn")

# 8. Admin role management, metrics
post(adm, f"/admin/users/{uid}/role", {"role": "assessor"}, "/admin")
with app.app_context():
    check(User.query.get(uid).role == "assessor", "admin promotes user to assessor")
    User.query.get(uid).role = "candidate"; db.session.commit()
check("Assessments completed" in adm.get("/admin").get_data(as_text=True), "admin sees success indicators")

# 9. Data rights
r = c.get("/account/export")
check(r.status_code == 200 and b"Electrical installation" in r.data, "candidate exports data as JSON")
r = post(c, "/account/delete", {"password": "longpassword1"}, "/account")
with app.app_context():
    check(User.query.filter_by(email="test@example.org").first() is None, "account deleted")
check(not os.listdir(os.environ["UPLOAD_FOLDER"]) or all("wiring" not in f for f in os.listdir(os.environ["UPLOAD_FOLDER"])), "files removed")

print(f"\nAll {ok} checks passed.")
