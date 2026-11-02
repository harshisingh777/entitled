"""HTTP API for the Entitled PWA, plus the mock portal."""
import base64
import time
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import agent, clock, config, gate, llm, nlu, ocr, portal, tools, views, voice
from .db import Application, Household, SessionLocal, init_db
from .engine.rules import load_catalog, load_schemes
from .seed import create_household, seed_operator_households

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_AUDIO_BYTES = 12 * 1024 * 1024


def _poll() -> None:
    db = SessionLocal()
    try:
        tools.poll_statuses(db)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    db = SessionLocal()
    try:
        seed_operator_households(db)
    finally:
        db.close()
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(_poll, "interval", seconds=config.POLL_SECONDS, id="status_poll", coalesce=True, max_instances=1)
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="Entitled", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?", allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")
app.include_router(portal.router)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _household(db: Session, household_id: str) -> Household:
    household = db.get(Household, household_id)
    if not household:
        raise HTTPException(404, "Household not found")
    return household


def _application(db: Session, application_id: str) -> Application:
    application = db.get(Application, application_id)
    if not application:
        raise HTTPException(404, "Application not found")
    return application


class NewHousehold(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    village: str | None = Field(default=None, max_length=120)
    operator: str | None = Field(default=None, max_length=120)


class ChatTurn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class DocumentState(BaseModel):
    have: bool


class FieldEdit(BaseModel):
    value: str = Field(min_length=1, max_length=300)


class StartForm(BaseModel):
    scheme_id: str


class Speak(BaseModel):
    text: str = Field(min_length=1, max_length=2500)
    language: str = "en-IN"


class Advance(BaseModel):
    days: int = Field(ge=1, le=60)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/config")
def client_config():
    return {
        "voice": voice.providers(), "llm": llm.available(), "ocr": "sarvam_vision" if config.SARVAM_API_KEY else "rapidocr",
        "sms": "twilio" if config.TWILIO_ACCOUNT_SID else "simulated", "schemes": len(load_schemes()),
    }


@app.get("/api/schemes")
def schemes():
    return [{k: s[k] for k in ("id", "name", "level", "benefit", "source_url", "last_verified", "verification")} for s in load_schemes().values()]


@app.post("/api/households", status_code=201)
def new_household(body: NewHousehold, db: Session = Depends(get_db)):
    household = create_household(db, village=body.village, operator=body.operator, name=body.name)
    return views.household_view(db, household)


@app.get("/api/households/{household_id}")
def get_household(household_id: str, db: Session = Depends(get_db)):
    return views.household_view(db, _household(db, household_id))


@app.post("/api/households/{household_id}/chat")
def chat(household_id: str, body: ChatTurn, db: Session = Depends(get_db)):
    household = _household(db, household_id)
    started = time.perf_counter()
    reply = agent.handle_turn(db, household, body.text)
    return {"reply": reply, "agent_ms": round((time.perf_counter() - started) * 1000), "state": views.household_view(db, household)}


@app.post("/api/households/{household_id}/session")
def new_session(household_id: str, db: Session = Depends(get_db)):
    household = _household(db, household_id)
    reply = agent.resume_session(db, household)
    return {"reply": reply, "state": views.household_view(db, household)}


@app.post("/api/households/{household_id}/documents/{doc_id}")
def set_document(household_id: str, doc_id: str, body: DocumentState, db: Session = Depends(get_db)):
    household = _household(db, household_id)
    tools.set_fact(db, household, f"doc_{doc_id}", body.have, "confirmed")
    if doc_id == "bank_passbook" and body.have:
        tools.set_fact(db, household, "has_bank_account", True, "inferred")
    tools.audit(db, household.id, "set_document", {"doc": doc_id, "have": body.have}, {}, actor="applicant")
    db.commit()
    return views.household_view(db, household)


@app.post("/api/households/{household_id}/ocr")
def read_document(household_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    household = _household(db, household_id)
    # Not async: reading a document takes seconds, and every other request would wait on it.
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Image is over 8 MB")
    extracted = tools.ocr_document(db, household, data, file.filename or "document.jpg")
    del data
    if extracted["doc_type"] is None:
        hi = "यह दस्तावेज़ पढ़ नहीं पाई। साफ़ रोशनी में दोबारा फ़ोटो लीजिए।"
        en = "I could not read this document. Please take another photo in good light."
    else:
        hi = "दस्तावेज़ पढ़ लिया, जानकारी भर दी। फ़ोटो रखी नहीं गई।"
        en = "Document read and details filled in. The photo was not kept."
    agent._record(db, household, "agent", hi, en)
    db.commit()
    return {"extracted": extracted, "reply": {"hi": hi, "en": en}, "state": views.household_view(db, household)}


@app.patch("/api/households/{household_id}/facts/{key}")
def edit_fact(household_id: str, key: str, body: FieldEdit, db: Session = Depends(get_db)):
    household = _household(db, household_id)
    if key not in load_catalog()["profile_fields"]:
        raise HTTPException(400, "Only form details can be edited here. Eligibility answers change through the conversation.")
    value = body.value
    if key == "annual_income":
        # Rules compare this one as a number, so it must never be stored as text.
        amount = nlu.parse_money(value)
        if amount is None:
            raise HTTPException(422, "Could not read that amount")
        value = amount
    tools.set_fact(db, household, key, value, "confirmed")
    for application in household.applications:
        tools._sync_fields(application, household)
    tools.audit(db, household.id, "edit_fact", {"key": key}, {}, actor="applicant")
    db.commit()
    return views.household_view(db, household)


@app.post("/api/households/{household_id}/form")
def start_form(household_id: str, body: StartForm, db: Session = Depends(get_db)):
    household = _household(db, household_id)
    if body.scheme_id not in load_schemes():
        raise HTTPException(404, "Unknown scheme")
    reply = agent.begin_form(db, household, body.scheme_id)
    return {"reply": reply, "state": views.household_view(db, household)}


@app.post("/api/applications/{application_id}/confirm")
def confirm_tap(application_id: str, db: Session = Depends(get_db)):
    application = _application(db, application_id)
    household = _household(db, application.household_id)
    reply = agent.confirm_by_tap(db, household, application)
    return {"reply": reply, "state": views.household_view(db, household)}


@app.post("/api/applications/{application_id}/submit")
def submit(application_id: str, x_confirmation_token: str | None = Header(default=None), db: Session = Depends(get_db)):
    """The raw tool. Without a token it refuses, which the demo shows on purpose."""
    application = _application(db, application_id)
    household = _household(db, application.household_id)
    try:
        outcome = tools.submit_application(db, household, application, x_confirmation_token)
    except gate.GateRefused as refused:
        return JSONResponse(status_code=403, content={"code": refused.code, "hi": refused.hi, "en": refused.en})
    db.commit()
    return outcome


@app.get("/api/applications/{application_id}/frames/{index}")
def frame(application_id: str, index: int, db: Session = Depends(get_db)):
    application = _application(db, application_id)
    path = tools.frames_dir(application.id) / f"{index:02d}.jpg"
    if not 0 <= index < application.frames or not path.exists():
        raise HTTPException(404, "No such frame")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/api/applications/{application_id}/pdf")
def application_pdf(application_id: str, db: Session = Depends(get_db)):
    application = _application(db, application_id)
    path = tools.generate_pdf(db, application)
    db.commit()
    return FileResponse(path, media_type="application/pdf", filename=f"entitled-{application.scheme_id}.pdf")


@app.get("/api/operator/dashboard")
def dashboard(db: Session = Depends(get_db)):
    return views.operator_dashboard(db)


@app.get("/api/audit")
def audit_log(household_id: str | None = None, limit: int = 200, db: Session = Depends(get_db)):
    return views.audit_view(db, household_id, min(limit, 500))


@app.post("/api/demo/advance")
def advance_time(body: Advance, db: Session = Depends(get_db)):
    offset = clock.advance(db, body.days)
    changed = tools.poll_statuses(db)
    return {"offset_days": offset, "changed": changed, "now": clock.now(db).isoformat()}


@app.post("/api/voice/stt")
def speech_to_text(file: UploadFile = File(...)):
    audio = file.file.read(MAX_AUDIO_BYTES + 1)
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "Recording is too long")
    started = time.perf_counter()
    try:
        transcript, provider = voice.transcribe(audio, file.filename or "speech.webm", file.content_type or "audio/webm")
    except voice.NoVoiceProvider as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"text": transcript, "provider": provider, "ms": round((time.perf_counter() - started) * 1000)}


@app.post("/api/voice/tts")
def text_to_speech(body: Speak):
    started = time.perf_counter()
    try:
        audio, mime, provider = voice.synthesize(body.text, body.language)
    except voice.NoVoiceProvider as exc:
        raise HTTPException(503, str(exc)) from exc
    base64.b64decode(audio[:8] + "=" * (-len(audio[:8]) % 4))
    return {"audio": audio, "mime": mime, "provider": provider, "ms": round((time.perf_counter() - started) * 1000)}


__all__ = ["app", "ocr"]
