"""Load demo data for the hackathon demo.

    python seed.py          # adds demo users if the database is empty
    python seed.py --reset  # wipes the database first (needed after model changes)

All demo accounts use the password below. Change or remove them before any real use.
"""
import random
import sys
from datetime import timedelta

from app import app
from models import (
    Appeal,
    Application,
    Assessment,
    AuditLog,
    Evidence,
    Experience,
    Job,
    Notification,
    Shortlist,
    Skill,
    SkillTest,
    User,
    db,
    utcnow,
)

DEMO_PASSWORD = "SkillProof-demo-2026"

# email, name, role, organisation, headline, location, status, days_ago
DEMO_USERS = [
    ("admin@skillproof.test", "Grace Wanjiru", "admin", "SkillProof", "", "Nairobi", "active", 40),
    ("assessor@skillproof.test", "Dr. Samuel Otieno", "assessor", "Kenya Tech Assessors Network", "", "Nairobi", "active", 38),
    ("assessor2@skillproof.test", "Fatuma Ali", "assessor", "Refugee Skills Partnership", "", "Kakuma", "active", 36),
    ("employer@skillproof.test", "Peter Kamau", "employer", "Savannah Software Ltd", "", "Nairobi", "active", 30),
    ("amina@skillproof.test", "Amina Hassan", "candidate", "", "Full-stack developer, 6 years' experience", "Nairobi, Kenya", "active", 28),
    ("jean@skillproof.test", "Jean-Pierre Habimana", "candidate", "", "Network technician and IT support specialist", "Kakuma, Kenya", "active", 21),
    ("nyaruach@skillproof.test", "Nyaruach Gatluak", "candidate", "", "Registered midwife", "Dadaab, Kenya", "active", 18),
    ("omar@skillproof.test", "Omar Abdi", "candidate", "", "Electrician, commercial and solar installations", "Nairobi, Kenya", "active", 14),
    ("aline@skillproof.test", "Aline Uwase", "candidate", "", "Secondary school maths teacher", "Kalobeyei, Kenya", "active", 9),
    ("yusuf@skillproof.test", "Yusuf Mohamed", "candidate", "", "Accountant and bookkeeper", "Eastleigh, Nairobi", "active", 5),
    ("hiring@greenbuild.test", "Mercy Achieng", "employer", "GreenBuild Solar Kenya", "", "Mombasa", "pending", 2),
    ("david.assessor@skillproof.test", "David Kiprop", "assessor", "Kenya Medical Training College", "", "Eldoret", "pending", 1),
]


def run(reset=False):
    random.seed(7)
    with app.app_context():
        if reset:
            db.drop_all()
            db.create_all()
        if User.query.first():
            print("Database already has users; use --reset to start over.")
            return
        now = utcnow()
        users = {}
        for email, name, role, org, headline, loc, status, days in DEMO_USERS:
            u = User(email=email, full_name=name, role=role, organisation=org, headline=headline, location=loc,
                     status=status, email_verified=status == "active", created_at=now - timedelta(days=days, hours=random.randint(0, 20)),
                     last_login_at=now - timedelta(hours=random.randint(1, 90)) if status == "active" else None)
            u.set_password(DEMO_PASSWORD)
            u.session_version = 1
            db.session.add(u)
            users[email.split("@")[0]] = u
        users["hiring"].website = "https://greenbuild.example"
        users["david.assessor"].expertise = "Healthcare, nursing, midwifery"
        users["assessor"].expertise = "Software development, IT support & networking"
        users["assessor2"].expertise = "Healthcare, Teaching, Business & finance"
        db.session.flush()
        A1, A2 = users["assessor"], users["assessor2"]

        def skill(u, name, cat, lvl, yrs, status="self_declared", days=10, task="", desc=""):
            s = Skill(user_id=u.id, name=name, category=cat, claimed_level=lvl, years=yrs, status=status, description=desc,
                      task_response=task, created_at=now - timedelta(days=days + 2),
                      requested_at=now - timedelta(days=days) if status != "self_declared" else None)
            db.session.add(s)
            db.session.flush()
            return s

        def assess(s, assessor, scores, level, comments, days):
            total = sum(scores)
            a = Assessment(skill_id=s.id, assessor_id=assessor.id, score_knowledge=scores[0], score_practical=scores[1],
                           score_evidence=scores[2], score_communication=scores[3],
                           assessed_level=level if total >= 12 and min(scores) >= 2 else None,
                           outcome="verified" if total >= 12 and min(scores) >= 2 else "not_verified",
                           comments=comments, created_at=now - timedelta(days=days))
            db.session.add(a)
            db.session.flush()
            return a

        # --- Amina: strong, shared, identity verified
        amina = users["amina"]
        amina.bio = ("Software developer from Mogadishu. I built web systems for an NGO and a logistics company "
                     "before relocating. My university certificates were lost, but my code is on GitHub.")
        amina.consent_share, amina.consent_at = True, now - timedelta(days=20)
        amina.identity_verified, amina.verified_by_id, amina.verified_at = True, users["admin"].id, now - timedelta(days=19)
        db.session.add_all([
            Experience(user_id=amina.id, title="Backend developer", organisation="Horn Logistics", country="Somalia",
                       start_year=2018, end_year=2022, description="Built a Flask + MySQL dispatch system used by 40 drivers."),
            Experience(user_id=amina.id, title="Freelance web developer", country="Kenya", start_year=2023,
                       description="Websites and small business systems for local clients."),
        ])
        py = skill(amina, "Python / Flask web development", "Software development", 4, 6, "verified", 24,
                   "https://github.com/example/dispatch-system. A dispatch system for a logistics company. I chose SQLAlchemy "
                   "so we could move from SQLite to MySQL; tested with pytest (80% coverage).", "REST APIs, authentication, deployment on Linux.")
        sql = skill(amina, "SQL databases (MySQL)", "Software development", 4, 5, "verified", 23,
                    "Designed the schema for the dispatch system: normalised tables, indexes on lookups and nightly backups with mysqldump.")
        skill(amina, "React", "Software development", 3, 2)
        mentor = skill(amina, "Coding mentoring for beginners", "Teaching & training", 3, 3, "verified", 18,
                       "I ran weekly evening classes for 12 young people at a community centre: HTML basics, then a small "
                       "Python project. I checked understanding with short exit tasks each week.")
        assess(mentor, A2, (4, 3, 3, 5), 3, "Clear, learner-centred approach with good checks for understanding. "
                                           "Explains concepts simply.", 16)
        skill(amina, "Data analysis in Excel", "Business & finance", 3, 4)
        db.session.add(Evidence(user_id=amina.id, skill_id=py.id, title="Dispatch system source code", kind="portfolio",
                                link="https://github.com/example/dispatch-system", description="Main project from Horn Logistics (anonymised).",
                                uploaded_at=now - timedelta(days=25)))
        db.session.add(Evidence(user_id=amina.id, skill_id=sql.id, title="Reference from former manager", kind="reference",
                                description="Operations manager, Horn Logistics (contact on request).", uploaded_at=now - timedelta(days=24)))
        assess(py, A1, (4, 5, 4, 4), 4, "Well-structured code with clear separation of concerns and tests. Explained design trade-offs well.", 22)
        assess(sql, A2, (4, 4, 3, 4), 4, "Sound schema design and good understanding of indexing. Reference supports the claim.", 21)

        # --- Jean: pending
        jean = users["jean"]
        jean.bio = "Network technician with 8 years' experience in Goma. Cisco training certificate lost during displacement."
        net = skill(jean, "Network troubleshooting", "IT support & networking", 4, 8, "pending", 2,
                    "First I check whether one machine or all machines are affected and ping the gateway. If the gateway answers, "
                    "I check DNS with nslookup and try pinging 8.8.8.8 directly. Then I check the DHCP leases on the router, "
                    "since a full pool is a common cause, and the switch uplink. I'd use ipconfig /all, tracert and the router admin page.")
        win = skill(jean, "Windows desktop support", "IT support & networking", 4, 8, "verified", 15,
                    "Reimaged 30 laptops for an NGO office using WDS, joined them to the domain and set up group policies.")
        assess(win, A1, (4, 4, 3, 3), 4, "Practical, methodical answer showing real-world experience with deployment at scale.", 13)
        jean.consent_share, jean.consent_at = True, now - timedelta(days=12)
        db.session.add(Evidence(user_id=jean.id, skill_id=net.id, title="Photos of server room installation",
                                kind="work_sample", description="Cabling and rack installation I did in 2019.", uploaded_at=now - timedelta(days=3)))

        # --- Nyaruach: not verified + open appeal
        ny = users["nyaruach"]
        mid = skill(ny, "Midwifery", "Healthcare", 4, 10, "not_verified", 12,
                    "I supported a prolonged labour case at the clinic. I monitored with a partograph and referred to the doctor when progress stopped at 7 cm.")
        a3 = assess(mid, A2, (3, 2, 1, 3), None, "Good protocol awareness but the description is brief and no evidence was provided. "
                    "Please add more detail on interventions and any reference from a supervisor.", 8)
        db.session.add(Appeal(assessment_id=a3.id, user_id=ny.id, created_at=now - timedelta(days=4),
                              reason="I uploaded no evidence because my clinic records were destroyed. My former supervisor at the MSF "
                                     "clinic can confirm my work. Please consider an oral assessment."))

        # --- Omar: verified electrician, shared
        om = users["omar"]
        om.bio = "Licensed electrician in Somalia for 9 years. Specialise in commercial wiring and off-grid solar for clinics and schools."
        om.consent_share, om.consent_at = True, now - timedelta(days=6)
        el = skill(om, "Electrical installation", "Trades & vocational", 4, 9, "verified", 10,
                   "Installed a 5 kW off-grid solar system for a clinic: panel mounting, charge controller, battery bank, isolation and earthing.")
        assess(el, A1, (4, 4, 4, 3), 4, "Photos and detailed description show safe isolation and correct earthing practice.", 7)
        skill(om, "Solar PV design", "Trades & vocational", 3, 4, "pending", 1,
              "Sized a system for a school: load audit of 3.2 kWh/day, 4 peak sun hours, 1.2 kWp array with 10 kWh lithium storage.")
        db.session.add(Evidence(user_id=om.id, skill_id=el.id, title="Clinic solar installation photos", kind="work_sample", uploaded_at=now - timedelta(days=11)))

        # --- Aline: teacher, verified
        al = users["aline"]
        al.bio = "Taught mathematics for 7 years in Rwanda. Currently volunteering at a community school in Kalobeyei."
        al.consent_share, al.consent_at = True, now - timedelta(days=3)
        t = skill(al, "Mathematics teaching (secondary)", "Teaching & training", 4, 7, "verified", 6,
                  "45-minute lesson on simultaneous equations: objectives, worked examples, pair work and exit-ticket check.")
        assess(t, A2, (4, 4, 3, 4), 4, "Clear, well-structured lesson plan with good formative assessment.", 3)

        # --- Yusuf: new, self-declared only
        yu = users["yusuf"]
        yu.bio = "Bookkeeper for a trading company in Mogadishu for 5 years."
        skill(yu, "Bookkeeping & accounts", "Business & finance", 3, 5)
        db.session.add(Experience(user_id=yu.id, title="Bookkeeper", organisation="Hodan Trading", country="Somalia", start_year=2017, end_year=2022))

        # --- Skills tests for the skills waiting in the queue (bank questions, all answered)
        import json as _json

        from ai import QUESTION_BANK, SHORT_QUESTIONS
        for s, right, answers in [(net, 4, ["When ping to the gateway works but names fail, I check DNS settings with nslookup "
                                                "and compare with a working machine.", "I explain that DHCP is like a receptionist "
                                                "giving each computer a room number (an IP address) when it arrives."]),
                                  (Skill.query.filter_by(user_id=om.id, name="Solar PV design").first(), 5,
                                   ["I sized a clinic system: I listed every load in watt-hours, divided by peak sun hours "
                                    "and added 25% margin.", "A charge controller protects the battery like a tap that stops "
                                    "the tank overflowing."])]:
            bank = QUESTION_BANK[s.category]
            qs = {"mcq": [{"question": q, "options": o, "correct_index": c, "explanation": ""} for q, o, c in bank],
                  "short_questions": SHORT_QUESTIONS}
            ans = {f"q{i}": (q["correct_index"] if i < right else (q["correct_index"] + 1) % len(q["options"]))
                   for i, q in enumerate(qs["mcq"])}
            ans.update({f"s{i}": a for i, a in enumerate(answers)})
            db.session.add(SkillTest(skill_id=s.id, user_id=s.user_id, source="bank", questions_json=_json.dumps(qs),
                                     answers_json=_json.dumps(ans), mcq_score=right, mcq_total=len(qs["mcq"]),
                                     started_at=now - timedelta(days=3), submitted_at=now - timedelta(days=3)))

        # --- Job access, jobs and applications
        amina.job_access, amina.job_access_at = "granted", now - timedelta(days=15)
        om.job_access, om.job_access_at, om.job_access_note = "requested", now - timedelta(hours=20), \
            "Looking for solar installation work in Nairobi or Mombasa."
        emp = users["employer"]
        j1 = Job(employer_id=emp.id, title="Junior backend developer (Python)", category="Software development",
                 location="Nairobi", remote=True, job_type="full_time", salary="KES 90,000–120,000 / month",
                 required_skills="Python, SQL, REST APIs", min_level=3, status="open", approved_by=users["admin"].id,
                 created_at=now - timedelta(days=9), approved_at=now - timedelta(days=8),
                 description="Build and maintain APIs for our logistics clients. You'll work in a team of 6 with a mentor, "
                             "write tests and join code reviews. Flexible hours; laptop provided.")
        j2 = Job(employer_id=emp.id, title="IT support technician", category="IT support & networking",
                 location="Kakuma", job_type="contract", salary="KES 45,000 / month", required_skills="Networking, Windows support",
                 min_level=3, status="open", approved_by=users["admin"].id, created_at=now - timedelta(days=6),
                 approved_at=now - timedelta(days=5),
                 description="Six-month contract supporting computers and the network at a training centre in Kakuma. "
                             "Install and repair PCs, keep the network running and train staff on basic IT.")
        j3 = Job(employer_id=emp.id, title="Data entry assistant", category="Business & finance", location="Nairobi",
                 job_type="part_time", required_skills="Excel, Bookkeeping", min_level=2, status="pending",
                 created_at=now - timedelta(hours=6),
                 description="Part-time role entering invoices and reconciling payments in Excel, 20 hours a week, "
                             "with training provided.")
        db.session.add_all([j1, j2, j3])
        db.session.flush()
        from ai import match_score
        db.session.add(Application(job_id=j1.id, candidate_id=amina.id, status="interview", match=match_score(j1, amina),
                                   cover_note="I built a Flask and MySQL dispatch system used by 40 drivers and would love "
                                              "to grow with your team.", created_at=now - timedelta(days=4),
                                   updated_at=now - timedelta(days=1)))

        # --- Employer shortlist & views, notifications
        emp = users["employer"]
        db.session.add(Shortlist(employer_id=emp.id, candidate_id=amina.id, note="Strong backend: invite to interview", created_at=now - timedelta(days=5)))
        db.session.add(Shortlist(employer_id=emp.id, candidate_id=jean.id, created_at=now - timedelta(days=2)))
        for d in (19, 15, 11, 9, 6, 5, 3, 2, 1, 0):
            for cand in (amina, jean) if d % 2 else (amina,):
                db.session.add(AuditLog(actor_id=emp.id, action="profile_view_employer", subject_user_id=cand.id,
                                        detail="employer=Savannah Software Ltd", created_at=now - timedelta(days=d, hours=3)))
        for d in (8, 4, 1):
            db.session.add(AuditLog(action="profile_view_link", subject_user_id=amina.id, detail="viewer=anonymous",
                                    created_at=now - timedelta(days=d, hours=5)))
        for u in users.values():
            db.session.add(AuditLog(actor_id=u.id, action="register", subject_user_id=u.id, detail=f"role={u.role}", created_at=u.created_at))
        sol = Skill.query.filter_by(user_id=om.id, name="Solar PV design").first()
        notes = [
            (amina, "Great news: “Python / Flask web development” has been independently verified (17/20).", "success", 22, f"/skills/{py.id}"),
            (amina, "Your identity has been verified by SkillProof.", "success", 19, "/account"),
            (amina, "Savannah Software Ltd viewed your competency report.", "info", 1, "/my-access-log"),
            (amina, "Savannah Software Ltd: your application for “Junior backend developer (Python)” is now interview.", "success", 1, "/my-applications"),
            (jean, "Great news: “Windows desktop support” has been independently verified (14/20).", "success", 13, f"/skills/{win.id}"),
            (ny, "“Midwifery” was assessed but not yet verified. See the feedback.", "warning", 8, f"/skills/{mid.id}"),
            (A1, "New assessment request: Network troubleshooting (IT support & networking)", "info", 2, f"/review/{net.id}"),
            (A1, "New assessment request: Solar PV design (Trades & vocational)", "info", 1, f"/review/{sol.id}"),
            (users["admin"], "New employer account awaiting approval: Mercy Achieng", "warning", 2, f"/admin/users/{users['hiring'].id}"),
            (users["admin"], "New assessor account awaiting approval: David Kiprop", "warning", 1, f"/admin/users/{users['david.assessor'].id}"),
            (users["admin"], "New appeal from Nyaruach Gatluak on Midwifery", "warning", 4, "/admin/appeals"),
            (users["admin"], "Job access requested by Omar Abdi", "warning", 1, "/admin/verifications"),
            (users["admin"], "Job post awaiting approval: Data entry assistant (Savannah Software Ltd)", "warning", 0, "/admin/jobs"),
            (emp, "New applicant for “Junior backend developer (Python)”: Amina Hassan", "info", 4, f"/employer/jobs/{j1.id}"),
        ]
        for u, msg, kind, d, link in notes:
            db.session.add(Notification(user_id=u.id, message=msg, kind=kind, link=link, created_at=now - timedelta(days=d)))
        db.session.commit()
        print("Demo data loaded. All demo accounts use the password in seed.py (DEMO_PASSWORD).")
        for email, _name, role, *_rest in DEMO_USERS:
            print(f"  {role:<10} {_rest[3]:<8} {email}")


if __name__ == "__main__":
    run(reset="--reset" in sys.argv)
