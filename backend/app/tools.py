"""The agent's tools. Every call lands in the action log with PII masked."""
import json
import subprocess
import sys
import threading
from datetime import timedelta

from sqlalchemy.orm import Session

from . import clock, config, gate, jobs, ocr, portal
from .db import Application, AuditLog, Fact, Household, Notification, Reminder, StatusEvent
from .engine import documents as doc_engine
from .engine import planner, rules
from .privacy import mask_digits, mask_pii
from .sms import send_sms

SOURCE_CONFIDENCE = {"said": 0.9, "document": 0.95, "inferred": 0.6, "confirmed": 1.0}
BLOCK_OFFICE_REMINDER_DAYS = 10

STATUS_LABELS = {
    "draft": {"hi": "तैयारी में", "en": "Draft"},
    "filled": {"hi": "फॉर्म भरा गया", "en": "Form filled"},
    "awaiting_confirmation": {"hi": "आपकी पुष्टि बाकी", "en": "Awaiting your confirmation"},
    "submitted": {"hi": "जमा हुआ", "en": "Submitted"},
    "under_verification": {"hi": "जाँच में", "en": "Under verification"},
    "approved": {"hi": "मंज़ूर", "en": "Approved"},
    "first_instalment": {"hi": "पहली किस्त मिली", "en": "First instalment paid"},
}
SUBMITTED_STATES = ("submitted", "under_verification", "approved", "first_instalment")


def audit(db: Session, household_id: str | None, tool: str, inputs: dict, output: dict, actor: str = "agent", outcome: str = "ok") -> None:
    db.add(AuditLog(household_id=household_id, tool=tool, inputs=mask_pii(inputs), output=mask_pii(output),
                    actor=actor, outcome=outcome, created_at=clock.now(db)))


def facts_of(household: Household) -> dict:
    return {f.key: f.value for f in household.facts}


def set_fact(db: Session, household: Household, key: str, value, source: str) -> bool:
    """Stores a fact. A guess never overwrites something the person said or a document showed."""
    existing = next((f for f in household.facts if f.key == key), None)
    if existing:
        if source == "inferred" and existing.source != "inferred":
            return False
        changed = existing.value != value
        existing.value, existing.source = value, source
        existing.confidence = SOURCE_CONFIDENCE[source]
        existing.updated_at = clock.now(db)
        return changed
    household.facts.append(Fact(key=key, value=value, source=source, confidence=SOURCE_CONFIDENCE[source], updated_at=clock.now(db)))
    return True


def check_eligibility(db: Session, household: Household, log: bool = True) -> dict:
    result = rules.evaluate_all(facts_of(household))
    if log:
        audit(db, household.id, "check_eligibility", {"facts": len(household.facts)},
              {"counts": result["counts"], "annual_inr": result["totals"]["annual_inr"]})
    return result


def next_question(db: Session, household: Household) -> dict | None:
    skipped = set(household.agent_state.get("skipped", []))
    question = planner.next_question(facts_of(household), skipped)
    audit(db, household.id, "next_question", {"skipped": sorted(skipped)},
          {k: question[k] for k in ("attr", "undecided", "expected_resolved")} if question else {"attr": None})
    return question


def explain_rule(db: Session, household: Household, scheme_id: str) -> dict:
    result = rules.evaluate_scheme(rules.load_schemes()[scheme_id], facts_of(household))
    output = {"hi": rules.explain(result, "hi"), "en": rules.explain(result, "en"), "outcome": result["outcome"]}
    audit(db, household.id, "explain_rule", {"scheme": scheme_id}, {"outcome": result["outcome"]})
    return output


def plan_documents(db: Session, household: Household, results: list[dict], log: bool = True) -> dict:
    plan = doc_engine.plan_documents(results, facts_of(household))
    if log:
        audit(db, household.id, "plan_documents", {}, {"total": plan["total"], "missing": plan["missing"]})
    return plan


_document_saves = threading.Lock()


def ocr_document(db: Session, household: Household, data: bytes, filename: str) -> dict:
    return save_document(db, household, ocr.read_document(data, filename))


def save_document(db: Session, household: Household, parsed: dict) -> dict:
    """Stores what a document showed. Used for photos read here and for text read on the person's own phone."""
    applied = []
    # Reads run side by side, but saves take turns: two reads of one household would insert the same facts.
    with _document_saves:
        db.expire_all()
        for key, value in {**parsed["fields"], **parsed["facts"]}.items():
            set_fact(db, household, key, value, "document")
            applied.append(key)
        if parsed["doc_type"]:
            set_fact(db, household, f"doc_{parsed['doc_type']}", True, "document")
        audit(db, household.id, "ocr_document", {"file": "deleted after extraction", "engine": parsed["engine"]},
              {"doc_type": parsed["doc_type"], "fields": applied})
        db.commit()
    masked = dict(parsed["fields"])
    if "bank_account" in masked:
        masked["bank_account"] = mask_digits(masked["bank_account"])
    return {"doc_type": parsed["doc_type"], "fields": masked, "facts": parsed["facts"], "engine": parsed["engine"], "image_stored": False}


def form_fields(scheme_id: str, facts: dict) -> tuple[dict, list[str]]:
    values, missing = {}, []
    for field in rules.load_schemes()[scheme_id]["form"]:
        if facts.get(field) not in (None, ""):
            values[field] = str(facts[field])
        else:
            missing.append(field)
    return values, missing


def open_application(db: Session, household: Household, scheme_id: str) -> Application:
    for app in household.applications:
        if app.scheme_id == scheme_id:
            return app
    app = Application(household_id=household.id, scheme_id=scheme_id, status="draft", fields={}, documents=[], created_at=clock.now(db))
    household.applications.append(app)
    db.flush()
    audit(db, household.id, "open_application", {"scheme": scheme_id}, {"application": app.id})
    return app


def _sync_fields(app: Application, household: Household) -> bool:
    """Copies the profile onto the application. Any change voids the earlier confirmation."""
    facts = facts_of(household)
    values, _ = form_fields(app.scheme_id, facts)
    docs = [d for d in doc_engine.documents_for_scheme(app.scheme_id, facts) if facts.get(f"doc_{d}") is True]
    if values == app.fields and docs == app.documents:
        return False
    app.fields, app.documents = values, docs
    if app.status not in SUBMITTED_STATES:
        app.readback_hash = app.confirmed_hash = app.confirmed_by = None
        app.status = "draft"
    return True


def _agent_process(job: dict) -> dict:
    with jobs.heavy():
        process = subprocess.run(
            [sys.executable, "-m", "app.form_agent"], input=json.dumps(job, ensure_ascii=False).encode("utf-8"),
            capture_output=True, cwd=str(config.BACKEND), timeout=120,
        )
    if process.returncode != 0:
        raise RuntimeError(process.stderr.decode("utf-8", "replace")[-600:])
    return json.loads(process.stdout.decode("utf-8"))


def frames_dir(app_id: str):
    return config.DATA_DIR / "frames" / app_id


def fill_form(db: Session, household: Household, app: Application) -> dict:
    _sync_fields(app, household)
    db.flush()
    result = _agent_process({
        "action": "fill", "url": f"{config.INTERNAL_BASE_URL}/portal/{app.scheme_id}/form",
        "fields": app.fields, "out": str(frames_dir(app.id)),
    })
    matched = sum(result["readback"].get(k) == v for k, v in app.fields.items())
    app.frames = result["frames"]
    app.fill_accuracy = round(matched / max(len(app.fields), 1), 3)
    app.status = "filled"
    audit(db, household.id, "fill_form", {"scheme": app.scheme_id, "fields": list(app.fields)},
          {"frames": app.frames, "field_accuracy": app.fill_accuracy})
    return {"frames": app.frames, "accuracy": app.fill_accuracy}


def generate_pdf(db: Session, app: Application) -> str:
    path = config.DATA_DIR / "frames" / app.id / "application.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    _agent_process({"action": "pdf", "url": f"{config.INTERNAL_BASE_URL}/portal/{app.scheme_id}/print/{app.id}", "out": str(path)})
    audit(db, app.household_id, "generate_pdf", {"scheme": app.scheme_id}, {"ok": True})
    return str(path)


def read_back(db: Session, household: Household, app: Application) -> dict:
    """The summary a person must hear before anything can be sent. Recording it arms the gate."""
    _sync_fields(app, household)
    schemes, catalog = rules.load_schemes(), rules.load_catalog()
    name = schemes[app.scheme_id]["name"]
    account = app.fields.get("bank_account", "")
    docs_hi = ", ".join(catalog["documents"][d]["hi"] for d in app.documents) or "कोई नहीं"
    docs_en = ", ".join(catalog["documents"][d]["en"] for d in app.documents) or "none"
    person = app.fields.get("name", "")
    last4_hi = f" बैंक खाते के आख़िरी चार अंक: {' '.join(account[-4:])}।" if account else ""
    last4_en = f" Bank account ending: {' '.join(account[-4:])}." if account else ""
    app.readback_hash = gate.fields_hash(app.scheme_id, app.fields, app.documents)
    app.confirmed_hash = None
    app.status = "awaiting_confirmation"
    audit(db, household.id, "read_back", {"application": app.id}, {"documents": app.documents})
    return {
        "hi": f"अब पढ़कर सुनाती हूँ। योजना: {name['hi']}। नाम: {person}।{last4_hi} साथ में: {docs_hi}। सब सही हो तो बोलिए: हाँ, भेज दो।",
        "en": f"Let me read it back. Scheme: {name['en']}. Name: {person}.{last4_en} Attached: {docs_en}. If all of this is right, say: yes, send it.",
    }


def confirm_application(db: Session, household: Household, app: Application, method: str, actor: str) -> str:
    _sync_fields(app, household)
    digest = gate.fields_hash(app.scheme_id, app.fields, app.documents)
    if app.readback_hash != digest:
        audit(db, household.id, "confirm_application", {"application": app.id, "method": method},
              {"code": "not_read_back"}, actor=actor, outcome="refused")
        db.commit()
        raise gate.GateRefused("not_read_back", "पहले सारांश सुन लीजिए, फिर पुष्टि कीजिए।", "Please hear the summary first, then confirm.")
    app.confirmed_hash, app.confirmed_by = digest, f"{actor} ({method})"
    audit(db, household.id, "confirm_application", {"application": app.id, "method": method}, {"ok": True}, actor=actor)
    return gate.mint(app.id, digest, f"{actor} ({method})")


def submit_application(db: Session, household: Household, app: Application, token: str | None, actor: str = "agent") -> dict:
    """Refuses without a valid token. There is no code path around this check."""
    if app.status in SUBMITTED_STATES:
        return {"reference": app.reference, "status": app.status}
    _sync_fields(app, household)
    digest = gate.fields_hash(app.scheme_id, app.fields, app.documents)
    try:
        confirmed_by = gate.verify(token, app.id, digest)
        reference = portal.receive_submission(app.scheme_id, app.id, digest, token)
    except gate.GateRefused as refused:
        audit(db, household.id, "submit_application", {"application": app.id, "token": "present" if token else "absent"},
              {"code": refused.code}, actor=actor, outcome="refused")
        db.commit()
        raise
    now = clock.now(db)
    app.reference, app.submitted_at, app.status = reference, now, "submitted"
    app.events.append(StatusEvent(status="submitted", at=now))
    audit(db, household.id, "submit_application", {"application": app.id, "fields": app.fields},
          {"reference": reference}, actor=confirmed_by)
    schedule_reminder(db, household, app, BLOCK_OFFICE_REMINDER_DAYS, "block_office")
    return {"reference": reference, "status": app.status}


def schedule_reminder(db: Session, household: Household, app: Application, days: int, kind: str) -> None:
    due = clock.now(db) + timedelta(days=days)
    db.add(Reminder(application_id=app.id, kind=kind, due_at=due))
    app.due_at = due
    app.next_action = {
        "hi": f"{days} दिन बाद ब्लॉक कार्यालय में जाँच की स्थिति पूछें", "en": f"Check at the block office in {days} days",
    }
    audit(db, household.id, "schedule_reminder", {"application": app.id, "kind": kind, "days": days}, {"due": due.isoformat()})


def check_status(db: Session, household: Household, app: Application, log: bool = True) -> dict:
    if not app.submitted_at:
        return {"status": app.status, "days": 0}
    status = portal.status_for(app.submitted_at, clock.now(db))
    days = (clock.now(db) - app.submitted_at).days
    if status != app.status and portal.STATUS_ORDER.index(status) > portal.STATUS_ORDER.index(app.status):
        now = clock.now(db)
        for step in portal.STATUS_ORDER[portal.STATUS_ORDER.index(app.status) + 1 : portal.STATUS_ORDER.index(status) + 1]:
            app.events.append(StatusEvent(status=step, at=now))
        app.status = status
        _on_status_change(db, household, app)
    if log:
        audit(db, household.id, "check_status", {"reference": app.reference}, {"status": app.status, "days": days})
    return {"status": app.status, "days": days}


def _on_status_change(db: Session, household: Household, app: Application) -> None:
    name = rules.load_schemes()[app.scheme_id]["name"]
    label = STATUS_LABELS[app.status]
    if app.status in ("approved", "first_instalment"):
        app.due_at = None
        app.next_action = {"hi": "कोई काम बाकी नहीं, खाते में राशि देखते रहें", "en": "Nothing to do, watch your bank account"}
    notify(db, household, app.id, "status", f"{name['hi']}: अब स्थिति \"{label['hi']}\" है।", f"{name['en']}: status is now \"{label['en']}\".")


def notify(db: Session, household: Household, app_id: str | None, kind: str, hi: str, en: str) -> None:
    mobile = facts_of(household).get("mobile")
    delivery = send_sms(mobile, hi)
    db.add(Notification(household_id=household.id, application_id=app_id, kind=kind, hi=hi, en=en, delivery=delivery, created_at=clock.now(db)))


def poll_statuses(db: Session) -> int:
    """Run on a schedule: moves every live application forward and sends what has come due."""
    changed = 0
    apps = db.query(Application).filter(Application.status.in_(SUBMITTED_STATES)).all()
    for app in apps:
        household = db.get(Household, app.household_id)
        before = app.status
        check_status(db, household, app, log=False)
        changed += before != app.status
    now = clock.now(db)
    for reminder in db.query(Reminder).filter(Reminder.sent_at.is_(None), Reminder.due_at <= now).all():
        app = db.get(Application, reminder.application_id)
        household = db.get(Household, app.household_id)
        reminder.sent_at = now
        if app.status != "under_verification":
            continue
        name = rules.load_schemes()[app.scheme_id]["name"]
        days = (now - app.submitted_at).days
        app.next_action = {"hi": "ब्लॉक कार्यालय जाकर जाँच की स्थिति पूछें", "en": "Visit the block office and ask about verification"}
        app.due_at = reminder.due_at + timedelta(days=3)
        notify(db, household, app.id, "reminder",
               f"Entitled: {name['hi']} का आवेदन {days} दिन से जाँच में है। ब्लॉक कार्यालय जाने का समय आ गया है। संदर्भ: {app.reference}",
               f"Entitled: your {name['en']} application has been in verification for {days} days. Time to visit the block office. Ref: {app.reference}")
        audit(db, household.id, "send_reminder", {"application": app.id, "kind": reminder.kind}, {"days": days})
    db.commit()
    return changed
