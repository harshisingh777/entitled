"""Mock state portal: forms, submission and a status API. Clearly not a government site.

`receive_submission` is the one call to swap when a real portal API exists.
"""
import html
import random
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from . import clock, gate
from .db import Application, SessionLocal
from .engine.rules import load_catalog, load_schemes

router = APIRouter(prefix="/portal", tags=["mock portal"])

STATUS_ORDER = ["submitted", "under_verification", "approved", "first_instalment"]
VERIFICATION_AFTER_DAYS, APPROVED_AFTER_DAYS, INSTALMENT_AFTER_DAYS = 1, 18, 30


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def status_for(submitted_at: datetime, now: datetime) -> str:
    days = (now - submitted_at).days
    if days >= INSTALMENT_AFTER_DAYS:
        return "first_instalment"
    if days >= APPROVED_AFTER_DAYS:
        return "approved"
    if days >= VERIFICATION_AFTER_DAYS:
        return "under_verification"
    return "submitted"


def receive_submission(scheme_id: str, application_id: str, digest: str, token: str | None) -> str:
    """Portal side of the gate: refuses anything without a valid confirmation."""
    gate.verify(token, application_id, digest)
    return f"MOCK-{scheme_id[:6].upper()}-{random.randint(100000, 999999)}"


_STYLE = """
@font-face{font-family:'Noto Sans Devanagari';src:url('/static/fonts/noto-sans-devanagari.woff2') format('woff2');font-weight:400 700}
*{box-sizing:border-box}body{margin:0;background:#eef0f3;color:#1a1f2b;font:15px/1.5 Arial,'Noto Sans Devanagari','Nirmala UI',sans-serif}
.banner{background:#7a2e0e;color:#fff;padding:8px 16px;font-weight:600;text-align:center}
header{background:#22375a;color:#fff;padding:14px 20px}header h1{margin:0;font-size:19px}header p{margin:2px 0 0;font-size:13px;opacity:.85}
main{max-width:760px;margin:16px auto;background:#fff;border:1px solid #c7ccd6;padding:20px}
h2{font-size:16px;border-bottom:2px solid #22375a;padding-bottom:6px;margin:0 0 14px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px 16px}label{display:block;font-weight:600;font-size:13.5px;margin-bottom:3px}
input{width:100%;padding:8px 10px;border:1px solid #8f96a3;border-radius:2px;font:inherit;background:#fbfbfc}input:focus{outline:2px solid #22375a}
.btn{margin-top:16px;padding:10px 18px;background:#22375a;color:#fff;border:0;font:inherit;font-weight:600}.note{font-size:12.5px;color:#4a5160;margin-top:12px}
dl{display:grid;grid-template-columns:1fr 1.4fr;gap:8px 14px;margin:0}dt{font-weight:600}dd{margin:0;border-bottom:1px dotted #8f96a3}
@media(max-width:600px){.grid{grid-template-columns:1fr}}
"""


def _page(title: str, body: str) -> str:
    return (
        f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width,initial-scale=1'><title>{html.escape(title)}</title>"
        f"<style>{_STYLE}</style></head><body>"
        "<div class='banner'>DEMO PORTAL, NOT A GOVERNMENT SITE</div>"
        f"<header><h1>{html.escape(title)}</h1><p>Entitled mock portal</p></header><main>{body}</main></body></html>"
    )


def _scheme_or_404(scheme_id: str) -> dict:
    scheme = load_schemes().get(scheme_id)
    if not scheme:
        raise HTTPException(404, "Unknown scheme")
    return scheme


@router.get("/{scheme_id}/form", response_class=HTMLResponse)
def form_page(scheme_id: str):
    scheme = _scheme_or_404(scheme_id)
    catalog = load_catalog()["profile_fields"]
    inputs = "".join(
        f"<div><label for='{f}'>{html.escape(catalog[f]['en'])}</label>"
        f"<input id='{f}' name='{f}' autocomplete='off'></div>"
        for f in scheme["form"]
    )
    body = (
        f"<h2>Application form</h2><form id='application' onsubmit='return false'><div class='grid'>{inputs}</div>"
        "<button class='btn' type='button' disabled>Submit (only after confirmation)</button>"
        "<p class='note'>The agent cannot submit by itself. This portal takes no application without the applicant's confirmation.</p></form>"
    )
    return _page(scheme["name"]["en"], body)


@router.get("/{scheme_id}/print/{application_id}", response_class=HTMLResponse)
def print_page(scheme_id: str, application_id: str, db: Session = Depends(get_db)):
    scheme = _scheme_or_404(scheme_id)
    app = db.get(Application, application_id)
    if not app:
        raise HTTPException(404, "Unknown application")
    catalog = load_catalog()
    rows = "".join(
        f"<dt>{html.escape(catalog['profile_fields'][k]['en'])}</dt>"
        f"<dd>{html.escape(str(app.fields.get(k, '')))}</dd>"
        for k in scheme["form"]
    )
    docs = "".join(f"<li>{html.escape(catalog['documents'][d]['en'])}</li>" for d in app.documents)
    body = (
        f"<h2>Pre-filled application</h2><dl>{rows}</dl>"
        f"<h2 style='margin-top:20px'>Documents to attach</h2><ul>{docs}</ul>"
        f"<p class='note'>For submission at the block office. The department makes the final eligibility decision. Source: {html.escape(scheme['source_url'])}</p>"
        "<p style='margin-top:36px'>Applicant's signature or thumbprint: ____________________ &nbsp; Date: ____________</p>"
    )
    return _page(scheme["name"]["en"], body)


@router.post("/api/{scheme_id}/submit")
async def submit_endpoint(scheme_id: str, request: Request, x_confirmation_token: str | None = Header(default=None), db: Session = Depends(get_db)):
    payload = await request.json()
    app = db.get(Application, payload.get("application_id", ""))
    if not app or app.scheme_id != scheme_id:
        raise HTTPException(404, "Unknown application")
    digest = gate.fields_hash(app.scheme_id, app.fields, app.documents)
    try:
        return {"reference": receive_submission(scheme_id, app.id, digest, x_confirmation_token)}
    except gate.GateRefused as refused:
        raise HTTPException(403, {"code": refused.code, "hi": refused.hi, "en": refused.en}) from refused


@router.get("/api/status/{reference}")
def status_endpoint(reference: str, db: Session = Depends(get_db)):
    app = db.query(Application).filter_by(reference=reference).first()
    if not app or not app.submitted_at:
        raise HTTPException(404, "Unknown reference")
    return {"reference": reference, "status": status_for(app.submitted_at, clock.now(db))}
