"""Load demo data for the hackathon demo.

    python seed.py          # adds demo users if the database is empty
    python seed.py --reset  # wipes the database first

All demo accounts use the password below. Change or remove them before any real use.
"""
import sys
from datetime import timedelta

from app import app
from models import Appeal, Assessment, AuditLog, Evidence, Experience, Skill, User, db, utcnow

DEMO_PASSWORD = "SkillProof-demo-2026"

DEMO_USERS = [
    # email, name, role, organisation, headline, location
    ("admin@skillproof.test", "Grace Wanjiru", "admin", "SkillProof", "", "Nairobi"),
    ("assessor@skillproof.test", "Dr. Samuel Otieno", "assessor", "Kenya Tech Assessors Network", "", "Nairobi"),
    ("assessor2@skillproof.test", "Fatuma Ali", "assessor", "Refugee Skills Partnership", "", "Kakuma"),
    ("employer@skillproof.test", "Peter Kamau", "employer", "Savannah Software Ltd", "", "Nairobi"),
    ("amina@skillproof.test", "Amina Hassan", "candidate", "", "Full-stack developer, 6 years' experience", "Nairobi, Kenya"),
    ("jean@skillproof.test", "Jean-Pierre Habimana", "candidate", "", "Network technician and IT support specialist", "Kakuma, Kenya"),
    ("nyaruach@skillproof.test", "Nyaruach Gatluak", "candidate", "", "Registered midwife", "Dadaab, Kenya"),
]


def run(reset=False):
    with app.app_context():
        if reset:
            db.drop_all()
            db.create_all()
        if User.query.first():
            print("Database already has users; use --reset to start over.")
            return
        users = {}
        for email, name, role, org, headline, loc in DEMO_USERS:
            u = User(email=email, full_name=name, role=role, organisation=org, headline=headline, location=loc)
            u.set_password(DEMO_PASSWORD)
            db.session.add(u)
            users[email.split("@")[0]] = u
        db.session.flush()
        now = utcnow()

        amina = users["amina"]
        amina.bio = ("Software developer from Mogadishu. I built web systems for an NGO and a logistics company "
                     "before relocating. My university certificates were lost, but my code is on GitHub.")
        amina.consent_share, amina.consent_at = True, now - timedelta(days=3)
        db.session.add_all([
            Experience(user_id=amina.id, title="Backend developer", organisation="Horn Logistics", country="Somalia",
                       start_year=2018, end_year=2022, description="Built a Flask + MySQL dispatch system used by 40 drivers."),
            Experience(user_id=amina.id, title="Freelance web developer", country="Kenya", start_year=2023,
                       description="Websites and small business systems for local clients."),
        ])
        py = Skill(user_id=amina.id, name="Python / Flask web development", category="Software development",
                   claimed_level=4, years=6, status="verified", requested_at=now - timedelta(days=6),
                   description="REST APIs, authentication, deployment on Linux.",
                   task_response="https://github.com/example/dispatch-system. A dispatch system for a logistics company. "
                                 "I chose SQLAlchemy so we could move from SQLite to MySQL; tested with pytest (80% coverage).")
        sql = Skill(user_id=amina.id, name="SQL databases (MySQL)", category="Software development", claimed_level=4,
                    years=5, status="verified", requested_at=now - timedelta(days=6),
                    task_response="Designed the schema for the dispatch system: normalised tables, indexes on lookups, "
                                  "and nightly backups with mysqldump. Example queries are in the repo /sql folder.")
        react = Skill(user_id=amina.id, name="React", category="Software development", claimed_level=3, years=2)
        db.session.add_all([py, sql, react])
        db.session.flush()
        db.session.add(Evidence(user_id=amina.id, skill_id=py.id, title="Dispatch system source code", kind="portfolio",
                                link="https://github.com/example/dispatch-system",
                                description="Main project from Horn Logistics (anonymised)."))
        db.session.add(Evidence(user_id=amina.id, skill_id=sql.id, title="Reference from former manager", kind="reference",
                                description="Contact: operations manager, Horn Logistics (email on request)."))
        a1 = Assessment(skill_id=py.id, assessor_id=users["assessor"].id, score_knowledge=4, score_practical=5,
                        score_evidence=4, score_communication=4, assessed_level=4, outcome="verified",
                        created_at=now - timedelta(days=4),
                        comments="Well-structured code with clear separation of concerns and tests. Explained design trade-offs well.")
        a2 = Assessment(skill_id=sql.id, assessor_id=users["assessor2"].id, score_knowledge=4, score_practical=4,
                        score_evidence=3, score_communication=4, assessed_level=4, outcome="verified",
                        created_at=now - timedelta(days=4),
                        comments="Sound schema design and good understanding of indexing. Reference supports the claim.")
        db.session.add_all([a1, a2])

        jean = users["jean"]
        jean.bio = "Network technician with 8 years' experience in Goma. Cisco training certificate lost during displacement."
        net = Skill(user_id=jean.id, name="Network troubleshooting", category="IT support & networking", claimed_level=4,
                    years=8, status="pending", requested_at=now - timedelta(days=1),
                    task_response="First I check whether one machine or all machines are affected and ping the gateway. "
                                  "If the gateway answers, I check DNS with nslookup and try pinging 8.8.8.8 directly. "
                                  "Then I check the DHCP leases on the router, since a full pool is a common cause, and "
                                  "the switch uplink and its port lights. I'd use ipconfig /all, tracert and the router admin page.")
        db.session.add(net)
        db.session.add(Skill(user_id=jean.id, name="Windows desktop support", category="IT support & networking",
                             claimed_level=4, years=8))
        db.session.flush()
        db.session.add(Evidence(user_id=jean.id, skill_id=net.id, title="Photos of server room installation",
                                kind="work_sample", description="Cabling and rack installation I did in 2019."))

        ny = users["nyaruach"]
        mid = Skill(user_id=ny.id, name="Midwifery", category="Healthcare", claimed_level=4, years=10, status="not_verified",
                    requested_at=now - timedelta(days=5), task_response="I supported a prolonged labour case at the clinic. "
                    "I monitored with a partograph and referred to the doctor when progress stopped at 7 cm.")
        db.session.add(mid)
        db.session.flush()
        a3 = Assessment(skill_id=mid.id, assessor_id=users["assessor2"].id, score_knowledge=3, score_practical=2,
                        score_evidence=1, score_communication=3, outcome="not_verified", created_at=now - timedelta(days=2),
                        comments="Good protocol awareness but the description is brief and no evidence was provided. "
                                 "Please add more detail on interventions and any reference from a supervisor.")
        db.session.add(a3)
        db.session.flush()
        db.session.add(Appeal(assessment_id=a3.id, user_id=ny.id,
                              reason="I uploaded no evidence because my clinic records were destroyed. My former supervisor "
                                     "at the MSF clinic can confirm my work. Please consider an oral assessment."))
        db.session.add(AuditLog(actor_id=users["employer"].id, action="profile_view_employer", subject_user_id=amina.id,
                                detail="employer=Savannah Software Ltd"))
        db.session.commit()
        print(f"Demo data loaded. All demo accounts use the password in seed.py (DEMO_PASSWORD).")
        for email, name, role, *_ in DEMO_USERS:
            print(f"  {role:<10} {email}")


if __name__ == "__main__":
    run(reset="--reset" in sys.argv)
