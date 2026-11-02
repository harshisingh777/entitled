"""The API with the browser agent stubbed. test_e2e.py runs the same journey with the real one."""
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import gate, tools
from app.db import Application, AuditLog, SessionLocal
from app.main import app
from app.privacy import mask_pii

SAMPLES = Path(__file__).resolve().parents[1] / "app" / "static" / "samples"
INTRO = "मेरा नाम कमला देवी है, मैं 58 साल की विधवा हूँ, रायबरेली के गाँव में रहती हूँ। BPL कार्ड है। बेटे के पास 1.2 एकड़ ज़मीन है और पोती 6 साल की है। सालाना कमाई 40 हज़ार है"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def no_browser(monkeypatch):
    def fake(job):
        return {"frames": len(job.get("fields", {})) + 1, "readback": job.get("fields", {})}
    monkeypatch.setattr(tools, "_agent_process", fake)


def say(client, household_id, text):
    response = client.post(f"/api/households/{household_id}/chat", json={"text": text})
    assert response.status_code == 200, response.text
    return response.json()


def ready_for_confirmation(client):
    """Drives one household all the way to the read-back."""
    household_id = client.post("/api/households", json={}).json()["household"]["id"]
    turn = say(client, household_id, INTRO)
    for _ in range(40):
        state = turn["state"]["household"]
        if state["stage"] == "CONFIRM":
            return household_id, turn
        expected = state["expected"]
        if state["pending_digit"]:
            text = "हाँ"
        elif state["pending_field"]:
            text = {"guardian_name": "रमेश कुमार", "dob": "15/03/1968", "address": "ग्राम बछरावां", "mobile": "9876543210",
                    "aadhaar_last4": "4821", "bank_account": "100200300412", "ifsc": "DEMO0001234"}[state["pending_field"]]
        elif expected == "start_form":
            text = "हाँ"
        elif expected == "doc_income_certificate":
            text = "नहीं"
        elif expected and expected.startswith("doc_"):
            text = "नहीं" if expected == "doc_birth_certificate" else "हाँ"
        elif expected in ("has_lpg", "has_pucca_house", "formal_income_screen", "rare_circumstances"):
            text = "नहीं"
        elif expected == "has_bank_account":
            text = "हाँ"
        else:
            pytest.fail(f"Unhandled prompt: {state} / {turn['reply']}")
        turn = say(client, household_id, text)
    pytest.fail("Never reached the confirmation stage")


def _app_id(turn):
    return next(a["id"] for a in turn["state"]["applications"] if a["awaiting_confirmation"])


def test_full_conversation_reaches_read_back_without_submitting(client):
    _, turn = ready_for_confirmation(client)
    applications = turn["state"]["applications"]
    assert all(a["reference"] is None for a in applications)
    assert "हाँ, भेज दो" in turn["reply"]["hi"]
    assert "0 4 1 2" in turn["reply"]["hi"]


def test_kamla_totals_and_pension_is_recommended(client):
    _, turn = ready_for_confirmation(client)
    assert turn["state"]["eligibility"]["totals"]["annual_inr"] == 18000
    assert turn["state"]["received_annual_inr"] == 0
    assert turn["state"]["applications"][0]["scheme_id"] == "up_nirashrit_mahila"


def test_submit_without_token_is_refused_and_logged(client):
    _, turn = ready_for_confirmation(client)
    application_id = _app_id(turn)
    response = client.post(f"/api/applications/{application_id}/submit")
    assert response.status_code == 403
    assert response.json()["code"] == "missing_confirmation"
    with SessionLocal() as db:
        assert db.get(Application, application_id).reference is None
        refused = db.query(AuditLog).filter_by(tool="submit_application", outcome="refused").all()
        assert any(r.inputs.get("application") == application_id for r in refused)


def test_forged_and_foreign_tokens_are_refused(client):
    _, first = ready_for_confirmation(client)
    _, second = ready_for_confirmation(client)
    target = _app_id(first)
    with SessionLocal() as db:
        other = db.get(Application, _app_id(second))
        foreign = gate.mint(other.id, gate.fields_hash(other.scheme_id, other.fields, other.documents), "x")
    assert client.post(f"/api/applications/{target}/submit", headers={"x-confirmation-token": "forged"}).status_code == 403
    response = client.post(f"/api/applications/{target}/submit", headers={"x-confirmation-token": foreign})
    assert response.status_code == 403 and response.json()["code"] == "wrong_application"


def test_bare_yes_does_not_submit(client):
    household_id, _ = ready_for_confirmation(client)
    turn = say(client, household_id, "हाँ")
    assert all(a["reference"] is None for a in turn["state"]["applications"])
    assert "भेज दो" in turn["reply"]["hi"]


def test_refusal_keeps_everything_unsent(client):
    household_id, _ = ready_for_confirmation(client)
    turn = say(client, household_id, "नहीं, मत भेजो")
    assert all(a["reference"] is None for a in turn["state"]["applications"])


def test_spoken_confirmation_submits_with_a_reference(client):
    household_id, _ = ready_for_confirmation(client)
    turn = say(client, household_id, "हाँ, भेज दो")
    submitted = turn["state"]["applications"][0]
    assert submitted["status"] == "submitted"
    assert submitted["reference"].startswith("MOCK-")
    assert submitted["confirmed_by"] == "applicant (voice)"
    assert submitted["due_at"]


def test_tap_confirmation_submits(client):
    _, turn = ready_for_confirmation(client)
    response = client.post(f"/api/applications/{_app_id(turn)}/confirm")
    assert response.json()["state"]["applications"][0]["confirmed_by"] == "applicant (tap)"


def test_any_field_change_voids_the_confirmation(client):
    household_id, turn = ready_for_confirmation(client)
    application_id = _app_id(turn)
    with SessionLocal() as db:
        application = db.get(Application, application_id)
        token = gate.mint(application.id, gate.fields_hash(application.scheme_id, application.fields, application.documents), "applicant")
    edited = client.patch(f"/api/households/{household_id}/facts/mobile", json={"value": "9000000001"})
    assert edited.status_code == 200
    application_view = next(a for a in edited.json()["applications"] if a["id"] == application_id)
    assert application_view["status"] == "draft"
    response = client.post(f"/api/applications/{application_id}/submit", headers={"x-confirmation-token": token})
    assert response.status_code == 403 and response.json()["code"] == "fields_changed"
    tapped = client.post(f"/api/applications/{application_id}/confirm").json()
    assert next(a for a in tapped["state"]["applications"] if a["id"] == application_id)["reference"] is None


def test_every_submission_in_the_database_carries_a_confirmation(client):
    with SessionLocal() as db:
        submitted = db.query(Application).filter(Application.reference.isnot(None)).all()
        assert submitted
        assert all(a.confirmed_hash and a.confirmed_by for a in submitted)


def test_near_miss_flips_when_the_certificate_arrives(client):
    household_id, _ = ready_for_confirmation(client)
    turn = say(client, household_id, "हाँ, भेज दो")
    before = {r["id"]: r["outcome"] for r in turn["state"]["eligibility"]["results"]}
    assert before["up_kanya_sumangala"] == "near_miss"
    response = client.post(f"/api/households/{household_id}/documents/income_certificate", json={"have": True})
    after = {r["id"]: r["outcome"] for r in response.json()["eligibility"]["results"]}
    assert after["up_kanya_sumangala"] == "eligible"


def test_time_skip_moves_status_sends_reminder_and_agent_resumes(client):
    household_id, _ = ready_for_confirmation(client)
    say(client, household_id, "हाँ, भेज दो")
    client.post("/api/demo/advance", json={"days": 12})
    resumed = client.post(f"/api/households/{household_id}/session").json()
    assert "12 दिन से जाँच में" in resumed["reply"]["hi"]
    assert "ब्लॉक कार्यालय" in resumed["reply"]["hi"]
    state = resumed["state"]
    assert state["applications"][0]["status"] == "under_verification"
    assert any(n["kind"] == "reminder" and n["delivery"] == "simulated" for n in state["notifications"])
    client.post("/api/demo/advance", json={"days": 20})
    final = client.get(f"/api/households/{household_id}").json()
    assert final["applications"][0]["status"] == "first_instalment"
    assert final["received_annual_inr"] == 12000


def test_ocr_fills_profile_and_never_keeps_full_aadhaar(client):
    household_id = client.post("/api/households", json={}).json()["household"]["id"]
    with (SAMPLES / "aadhaar.jpg").open("rb") as image:
        response = client.post(f"/api/households/{household_id}/ocr", files={"file": ("aadhaar.jpg", image, "image/jpeg")})
    body = response.json()
    assert body["extracted"]["doc_type"] == "aadhaar"
    assert body["extracted"]["image_stored"] is False
    facts = {f["key"]: f for f in body["state"]["facts"]}
    assert facts["aadhaar_last4"]["value"] == "4821"
    assert facts["dob"]["value"] == "15/03/1968"
    assert facts["name"]["value"] == "Kamla Devi"
    assert facts["name"]["source"] == "document"
    assert "9999" not in response.text and "8888" not in response.text


def test_documents_read_at_the_same_time_all_save(client, monkeypatch):
    household_id = client.post("/api/households", json={}).json()["household"]["id"]
    together = threading.Barrier(4)

    def read(data, filename):
        together.wait(timeout=20)
        return {"doc_type": filename.removesuffix(".jpg"), "fields": {"name": "Kamla Devi", "district": "Raebareli"}, "facts": {}, "engine": "rapidocr"}
    monkeypatch.setattr(tools.ocr, "read_document", read)

    def upload(doc):
        return client.post(f"/api/households/{household_id}/ocr", files={"file": (f"{doc}.jpg", b"image", "image/jpeg")}).status_code
    with ThreadPoolExecutor(4) as pool:
        statuses = list(pool.map(upload, ["aadhaar", "ration_card", "bank_passbook", "land_record"]))
    assert statuses == [200, 200, 200, 200]
    facts = {f["key"] for f in client.get(f"/api/households/{household_id}").json()["facts"]}
    assert {"doc_aadhaar", "doc_ration_card", "doc_bank_passbook", "doc_land_record", "name", "district"} <= facts


def test_ocr_reads_passbook_and_masks_the_account_on_screen(client):
    household_id = client.post("/api/households", json={}).json()["household"]["id"]
    with (SAMPLES / "passbook.jpg").open("rb") as image:
        body = client.post(f"/api/households/{household_id}/ocr", files={"file": ("passbook.jpg", image, "image/jpeg")}).json()
    assert body["extracted"]["fields"]["ifsc"] == "DEMO0001234"
    assert body["extracted"]["fields"]["bank_account"] == "XXXX0412"
    facts = {f["key"]: f["value"] for f in body["state"]["facts"]}
    assert facts["bank_account"] == "XXXX0412"
    assert facts["has_bank_account"] is True


def test_action_log_masks_pii():
    masked = mask_pii({"fields": {"bank_account": "100200300412", "mobile": "9876543210", "name": "कमला"}, "note": "acct 100200300412"})
    assert masked["fields"]["bank_account"] == "XXXX0412"
    assert masked["fields"]["mobile"] == "XXXX3210"
    assert masked["fields"]["name"] == "कमला"
    assert "100200300412" not in masked["note"]


def test_action_log_never_holds_a_raw_account_number(client):
    response = client.get("/api/audit?limit=500")
    assert response.status_code == 200
    assert "100200300412" not in response.text and "9876543210" not in response.text


def test_operator_dashboard_has_thirty_seeded_households(client):
    body = client.get("/api/operator/dashboard").json()
    assert body["totals"]["households"] >= 30
    assert body["totals"]["pending"] > 0
    assert body["totals"]["submitted"] > 0
    assert {"action", "entitled_annual_inr", "missing_documents"} <= set(body["households"][0])


def test_why_question_gets_the_rule_trace(client):
    household_id = client.post("/api/households", json={}).json()["household"]["id"]
    say(client, household_id, INTRO)
    turn = say(client, household_id, "वृद्धावस्था पेंशन क्यों नहीं मिलेगी?")
    assert "2 साल बाद" in turn["reply"]["hi"]


def test_dont_know_moves_on_and_leaves_the_scheme_undecided(client):
    household_id = client.post("/api/households", json={}).json()["household"]["id"]
    first = client.get(f"/api/households/{household_id}").json()["household"]["expected"]
    turn = say(client, household_id, "पता नहीं")
    assert turn["state"]["household"]["expected"] != first


def test_unknown_routes_return_404(client):
    assert client.get("/api/households/missing").status_code == 404
    assert client.post("/api/applications/missing/submit").status_code == 404


def test_voice_without_keys_tells_the_client_to_use_the_browser(client):
    assert client.get("/api/config").json()["voice"]["mode"] == "browser"
    assert client.post("/api/voice/tts", json={"text": "नमस्ते"}).status_code == 503


def test_a_conversation_entirely_in_english_reaches_the_gate(client):
    household_id = client.post("/api/households", json={}).json()["household"]["id"]
    turn = say(client, household_id, "My name is Kamla Devi, I am a 58 year old widow, I live in a village in Raebareli. I have a BPL card. My son has 1.2 acres of land and my granddaughter is 6 years old. Our yearly income is 40 thousand.")
    fields = {"guardian_name": "Ramesh Kumar", "dob": "15/03/1968", "address": "Village Bachhrawan", "mobile": "9876543210",
              "aadhaar_last4": "4821", "bank_account": "100200300412", "ifsc": "DEMO0001234"}
    for _ in range(40):
        state = turn["state"]["household"]
        if state["stage"] == "CONFIRM":
            break
        if state["pending_digit"]:
            text = "Yes"
        elif state["pending_field"]:
            text = fields[state["pending_field"]]
        elif state["expected"] in ("doc_income_certificate", "doc_birth_certificate", "has_lpg", "has_pucca_house", "formal_income_screen", "rare_circumstances"):
            text = "No"
        else:
            text = "Yes"
        assert turn["reply"]["en"].isascii() or "₹" in turn["reply"]["en"], turn["reply"]["en"]
        turn = say(client, household_id, text)
    assert "yes, send it" in turn["reply"]["en"]
    assert turn["state"]["eligibility"]["totals"]["annual_inr"] == 18000
    done = say(client, household_id, "Yes, send it")
    assert done["state"]["applications"][0]["reference"].startswith("MOCK-")
    assert "Reference" in done["reply"]["en"]


def test_record_ids_survive_masking_even_when_they_are_all_digits():
    assert mask_pii({"application": "123456789012"})["application"] == "123456789012"
    assert mask_pii("id 123456789abc stays")  == "id 123456789abc stays"
