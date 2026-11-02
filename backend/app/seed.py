"""Synthetic households for operator mode. Everyone here is invented.

Their applications go through the real gate and are then back-dated, so the
"nothing is submitted without confirmation" invariant holds for seed data too.
"""
import random
from datetime import timedelta

from sqlalchemy.orm import Session

from . import agent, clock, portal, tools
from .db import Household, StatusEvent

OPERATOR = "Sunita Yadav (ASHA)"
_FEMALE = ["Savitri Devi", "Shanti Devi", "Geeta Kumari", "Meera Devi", "Rekha Yadav", "Suman Pal", "Urmila Devi", "Asha Kumari", "Parvati Devi", "Radha Gupta", "Kaushalya Devi", "Nirmala Pasi", "Seema Devi", "Lakshmi Devi", "Phoolmati"]
_MALE = ["Ramprasad Yadav", "Shivkumar Pal", "Mohan Lal", "Raghunath Pasi", "Dinesh Kumar", "Suresh Gupta", "Hariram", "Babulal", "Jagdish Prasad", "Ashok Kumar", "Rajendra Maurya", "Gangaram", "Vinod Kumar", "Chhotelal", "Kamlesh Pal"]
_VILLAGES = ["Bachhrawan", "Salon", "Unchahar", "Lalganj", "Dalmau", "Harchandpur", "Maharajganj", "Tiloi"]


def _persona(rng: random.Random, index: int) -> dict:
    female = index % 2 == 0
    age = rng.choice([24, 29, 34, 38, 43, 47, 52, 58, 61, 66, 72, 79])
    name = (_FEMALE if female else _MALE)[index // 2 % 15]
    girls = rng.choice([0, 0, 1, 1, 2, 3])
    year = 2026 - age
    facts = {
        "name": name, "guardian_name": rng.choice(_MALE), "dob": f"{rng.randint(1, 28):02d}/{rng.randint(1, 12):02d}/{year}",
        "address": f"Village {_VILLAGES[index % 8]}", "district": "Raebareli", "mobile": f"90000{index:05d}",
        "aadhaar_last4": f"{1000 + index}", "bank_account": f"1000000{index:05d}", "ifsc": "DEMO0000001",
        "age": age, "gender": "female" if female else "male", "is_widow": female and age >= 45 and rng.random() < 0.6,
        "state_up": True, "area": "rural", "bpl_card": rng.random() < 0.65, "annual_income": rng.choice([28000, 36000, 44000, 60000, 90000, 150000, 240000]),
        "owns_farmland": rng.random() < 0.55, "income_tax_payer": False, "govt_employee": rng.random() < 0.05,
        "girl_children_count": girls, "has_lpg": rng.random() < 0.5, "has_pucca_house": rng.random() < 0.4,
        "pregnant_or_lactating": female and age < 35 and rng.random() < 0.25, "traditional_artisan": rng.random() < 0.15,
        "has_bank_account": rng.random() < 0.9, "student_class_9plus": rng.random() < 0.25,
        "doc_income_certificate": rng.random() < 0.4, "doc_aadhaar": True, "doc_bank_passbook": rng.random() < 0.8,
        "doc_ration_card": rng.random() < 0.85, "doc_death_certificate": rng.random() < 0.7, "doc_birth_certificate": rng.random() < 0.4,
        "doc_land_record": rng.random() < 0.6, "doc_mcp_card": True, "doc_school_id": rng.random() < 0.6,
    }
    if facts["owns_farmland"]:
        facts["land_acres"] = rng.choice([0.5, 1.0, 1.5, 2.0, 3.0])
    if girls:
        facts["youngest_girl_age"] = rng.choice([2, 4, 6, 9, 12, 15])
        facts["girl_name"] = rng.choice(["Ananya", "Priya", "Neha", "Pooja", "Kajal"])
        facts["girl_dob"] = f"{rng.randint(1, 28):02d}/{rng.randint(1, 12):02d}/{2026 - facts['youngest_girl_age']}"
    return facts


def _submit_backdated(db: Session, household: Household, scheme_id: str, days_ago: int) -> None:
    app = tools.open_application(db, household, scheme_id)
    tools.read_back(db, household, app)
    token = tools.confirm_application(db, household, app, "seed", "seed data")
    tools.submit_application(db, household, app, token, actor="seed data")
    moved = clock.now(db) - timedelta(days=days_ago)
    app.submitted_at = moved
    for event in app.events:
        event.at = moved
    for reminder in db.query(tools.Reminder).filter_by(application_id=app.id).all():
        reminder.due_at = moved + timedelta(days=tools.BLOCK_OFFICE_REMINDER_DAYS)
        app.due_at = reminder.due_at
    household.stage = "TRACK"


def seed_operator_households(db: Session, count: int = 30) -> int:
    if db.query(Household).filter_by(is_seed=True).count():
        return 0
    rng = random.Random(42)
    now = clock.now(db)
    for index in range(count):
        household = Household(display_name=None, village=_VILLAGES[index % 8], operator=OPERATOR, is_seed=True, created_at=now,
                              stage="DOCS", agent_state={"docs_intro": True}, questions_asked=rng.randint(6, 11))
        db.add(household)
        db.flush()
        facts = _persona(rng, index)
        interview_open = index % 7 == 6
        for key, value in facts.items():
            if interview_open and key in ("is_widow", "annual_income", "bpl_card", "has_bank_account", "owns_farmland", "doc_income_certificate"):
                continue
            tools.set_fact(db, household, key, value, "said")
        if interview_open:
            household.stage = "INTERVIEW"
            continue
        result = tools.check_eligibility(db, household, log=False)
        usable = [r for r in result["results"] if r["outcome"] == "eligible" and not r.get("suppressed_by") and r["annual_inr"] > 0]
        if usable and index % 3 != 2:
            _submit_backdated(db, household, usable[0]["id"], rng.choice([2, 5, 8, 11, 13, 16, 20, 33]))
    db.flush()
    tools.poll_statuses(db)
    db.commit()
    return count


def create_household(db: Session, *, village: str | None = None, operator: str | None = None, name: str | None = None) -> Household:
    household = Household(display_name=name, village=village, operator=operator, created_at=clock.now(db), agent_state={})
    db.add(household)
    db.flush()
    agent.welcome(db, household)
    return household


__all__ = ["create_household", "seed_operator_households", "portal", "StatusEvent"]
