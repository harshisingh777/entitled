"""What the screens receive. Sensitive values are masked here, the single exit point."""
from sqlalchemy.orm import Session

from . import clock, tools
from .db import Application, AuditLog, Household, Message, Notification
from .engine.rules import ELIGIBLE, load_catalog, load_schemes
from .privacy import mask_digits

_MASK_IN_UI = {"bank_account"}


def _fact_label(key: str) -> dict:
    catalog = load_catalog()
    if key in catalog["questions"]:
        return catalog["questions"][key]["label"]
    if key in catalog["profile_fields"]:
        field = catalog["profile_fields"][key]
        return {"hi": field["hi"], "en": field["en"]}
    if key.startswith("doc_") and key[4:] in catalog["documents"]:
        doc = catalog["documents"][key[4:]]
        return {"hi": doc["hi"], "en": doc["en"]}
    return {"hi": key, "en": key}


def application_view(db: Session, app: Application) -> dict:
    scheme = load_schemes()[app.scheme_id]
    catalog = load_catalog()
    now = clock.now(db)
    return {
        "id": app.id, "scheme_id": app.scheme_id, "scheme_name": scheme["name"],
        "status": app.status, "status_label": tools.STATUS_LABELS[app.status],
        "reference": app.reference, "frames": app.frames, "fill_accuracy": app.fill_accuracy,
        "fields": [
            {"id": f, "label": {"hi": catalog["profile_fields"][f]["hi"], "en": catalog["profile_fields"][f]["en"]},
             "value": mask_digits(app.fields[f]) if f in _MASK_IN_UI and app.fields.get(f) else app.fields.get(f, "")}
            for f in scheme["form"]
        ],
        "documents": [{"id": d, "name": {"hi": catalog["documents"][d]["hi"], "en": catalog["documents"][d]["en"]}} for d in app.documents],
        "awaiting_confirmation": app.status == "awaiting_confirmation",
        "confirmed_by": app.confirmed_by,
        "next_action": app.next_action,
        "due_at": app.due_at.isoformat() if app.due_at else None,
        "overdue": bool(app.due_at and app.due_at < now and app.status == "under_verification"),
        "days_since_submission": (now - app.submitted_at).days if app.submitted_at else None,
        "events": [{"status": e.status, "label": tools.STATUS_LABELS[e.status], "at": e.at.isoformat()} for e in app.events],
    }


def household_view(db: Session, household: Household) -> dict:
    result = tools.check_eligibility(db, household, log=False)
    plan = tools.plan_documents(db, household, result["results"], log=False)
    schemes = load_schemes()
    received = sum(
        next((r["annual_inr"] for r in result["results"] if r["id"] == a.scheme_id), 0)
        for a in household.applications if a.status == "first_instalment"
    )
    messages = (db.query(Message).filter_by(household_id=household.id).order_by(Message.id).all())
    notifications = (db.query(Notification).filter_by(household_id=household.id).order_by(Notification.id.desc()).limit(30).all())
    facts = [
        {"key": f.key, "value": mask_digits(f.value) if f.key in _MASK_IN_UI else f.value, "source": f.source,
         "confidence": f.confidence, "label": _fact_label(f.key)}
        for f in household.facts
    ]
    agent = household.agent_state
    applied = {a.scheme_id: a.status for a in household.applications}
    for item in result["results"]:
        item["application_status"] = applied.get(item["id"])
    return {
        "household": {
            "id": household.id, "name": _name(household), "village": household.village, "operator": household.operator,
            "stage": household.stage, "questions_asked": household.questions_asked, "session_no": household.session_no,
            "expected": agent.get("expected"), "pending_field": agent.get("pending_field"),
            "pending_digit": bool(agent.get("pending_digit")), "active_scheme": agent.get("active_scheme"),
        },
        "facts": facts,
        "eligibility": result,
        "documents": plan,
        "scheme_count": len(schemes),
        "received_annual_inr": received,
        "applications": [application_view(db, a) for a in household.applications],
        "messages": [{"id": m.id, "role": m.role, "hi": m.hi, "en": m.en, "kind": m.kind, "at": m.created_at.isoformat()} for m in messages],
        "notifications": [{"id": n.id, "kind": n.kind, "hi": n.hi, "en": n.en, "delivery": n.delivery, "at": n.created_at.isoformat()} for n in notifications],
        "now": clock.now(db).isoformat(),
    }


def _name(household: Household) -> str | None:
    return next((f.value for f in household.facts if f.key == "name"), household.display_name)


def _pending_action(db: Session, household: Household, result: dict, plan: dict) -> dict:
    now = clock.now(db)
    for app in household.applications:
        if app.status == "under_verification" and app.due_at:
            name = load_schemes()[app.scheme_id]["name"]
            return {
                "kind": "follow_up", "hi": f"{name['hi']}: {(app.next_action or {}).get('hi', 'जाँच देखें')}", "en": f"{name['en']}: {(app.next_action or {}).get('en', 'check verification')}",
                "due_at": app.due_at.isoformat(), "overdue": app.due_at < now,
            }
    for app in household.applications:
        if app.status == "awaiting_confirmation":
            name = load_schemes()[app.scheme_id]["name"]
            return {"kind": "confirm", "hi": f"{name['hi']}: आवेदक की पुष्टि लें", "en": f"{name['en']}: get the applicant's confirmation", "due_at": None, "overdue": False}
    if result["counts"]["undecided"] and household.stage == "INTERVIEW":
        return {"kind": "interview", "hi": "बातचीत पूरी करें", "en": "Finish the interview", "due_at": None, "overdue": False}
    if plan["missing"]:
        catalog = load_catalog()["documents"][plan["missing"][0]]
        return {"kind": "document", "hi": f"{catalog['hi']} बनवाएँ", "en": f"Get the {catalog['en']}", "due_at": None, "overdue": False}
    started = {a.scheme_id for a in household.applications}
    open_scheme = next((r for r in result["results"] if r["outcome"] == ELIGIBLE and not r.get("suppressed_by") and r["id"] not in started), None)
    if open_scheme:
        return {"kind": "apply", "hi": f"{open_scheme['name']['hi']}: फॉर्म भरें", "en": f"{open_scheme['name']['en']}: fill the form", "due_at": None, "overdue": False}
    return {"kind": "none", "hi": "कोई काम बाकी नहीं", "en": "Nothing pending", "due_at": None, "overdue": False}


def operator_dashboard(db: Session) -> dict:
    rows, totals = [], {"households": 0, "entitled_annual_inr": 0, "received_annual_inr": 0, "overdue": 0, "pending": 0, "submitted": 0}
    for household in db.query(Household).order_by(Household.created_at).all():
        result = tools.check_eligibility(db, household, log=False)
        plan = tools.plan_documents(db, household, result["results"], log=False)
        action = _pending_action(db, household, result, plan)
        received = sum(
            next((r["annual_inr"] for r in result["results"] if r["id"] == a.scheme_id), 0)
            for a in household.applications if a.status == "first_instalment"
        )
        rows.append({
            "id": household.id, "name": _name(household) or "New household", "village": household.village,
            "stage": household.stage, "eligible": result["counts"][ELIGIBLE], "near_miss": result["counts"]["near_miss"],
            "entitled_annual_inr": result["totals"]["annual_inr"], "received_annual_inr": received,
            "missing_documents": len(plan["missing"]), "applications": len(household.applications), "action": action,
        })
        totals["households"] += 1
        totals["entitled_annual_inr"] += result["totals"]["annual_inr"]
        totals["received_annual_inr"] += received
        totals["overdue"] += action["overdue"]
        totals["pending"] += action["kind"] != "none"
        totals["submitted"] += sum(a.status in tools.SUBMITTED_STATES for a in household.applications)
    rows.sort(key=lambda r: (not r["action"]["overdue"], r["action"]["kind"] == "none", r["action"]["due_at"] or "9999"))
    return {"totals": totals, "households": rows, "now": clock.now(db).isoformat()}


def audit_view(db: Session, household_id: str | None = None, limit: int = 200) -> list[dict]:
    query = db.query(AuditLog)
    if household_id:
        query = query.filter_by(household_id=household_id)
    return [
        {"id": a.id, "household_id": a.household_id, "tool": a.tool, "inputs": a.inputs, "output": a.output,
         "actor": a.actor, "outcome": a.outcome, "at": a.created_at.isoformat()}
        for a in query.order_by(AuditLog.id.desc()).limit(limit).all()
    ]
