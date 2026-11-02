"""The demo journey against a real server with the real Playwright agent and real OCR."""
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import pytest

BACKEND = Path(__file__).resolve().parents[1]
SAMPLES = BACKEND / "app" / "static" / "samples"
ANSWERS = {"doc_income_certificate": "नहीं", "has_lpg": "नहीं", "has_pucca_house": "नहीं", "formal_income_screen": "नहीं", "rare_circumstances": "नहीं", "has_bank_account": "हाँ"}


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def api():
    port = _free_port()
    data_dir = tempfile.mkdtemp(prefix="entitled-e2e-")
    env = {**os.environ, "ENTITLED_DATA_DIR": data_dir, "DATABASE_URL": f"sqlite:///{Path(data_dir, 'e2e.db').as_posix()}",
           "BACKEND_PORT": str(port), "INTERNAL_BASE_URL": f"http://127.0.0.1:{port}"}
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)], cwd=BACKEND, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    client = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=120)
    try:
        for _ in range(60):
            try:
                if client.get("/api/health").status_code == 200:
                    break
            except httpx.TransportError:
                time.sleep(0.5)
        else:
            pytest.fail("Server did not start")
        yield client
    finally:
        client.close()
        server.terminate()
        server.wait(timeout=20)


def upload(api, household_id, name):
    with (SAMPLES / name).open("rb") as image:
        response = api.post(f"/api/households/{household_id}/ocr", files={"file": (name, image, "image/jpeg")})
    assert response.status_code == 200, response.text
    return response.json()


def say(api, household_id, text):
    response = api.post(f"/api/households/{household_id}/chat", json={"text": text})
    assert response.status_code == 200, response.text
    return response.json()


def test_kamla_demo_from_first_words_to_money(api):
    household_id = api.post("/api/households", json={}).json()["household"]["id"]

    turn = say(api, household_id, "मेरा नाम कमला देवी है, मैं 58 साल की विधवा हूँ, रायबरेली के गाँव में रहती हूँ। BPL कार्ड है। बेटे के पास 1.2 एकड़ ज़मीन है और पोती 6 साल की है। सालाना कमाई 40 हज़ार है")
    questions = 0
    while turn["state"]["household"]["stage"] == "INTERVIEW":
        turn = say(api, household_id, ANSWERS[turn["state"]["household"]["expected"]])
        questions += 1
    assert questions <= 6

    for name in ("ration_card.jpg", "aadhaar.jpg", "passbook.jpg"):
        extracted = upload(api, household_id, name)["extracted"]
        assert extracted["doc_type"] and extracted["engine"] == "rapidocr"

    # Answer whatever is still open on the checklist, then let the agent run the form.
    replies = {"guardian_name": "रमेश कुमार", "mobile": "9876543210", "address": "ग्राम बछरावां"}
    turn = say(api, household_id, "फॉर्म भरो")
    for _ in range(25):
        state = turn["state"]["household"]
        if state["stage"] == "CONFIRM":
            break
        if state["pending_digit"]:
            turn = say(api, household_id, "हाँ")
        elif state["pending_field"]:
            turn = say(api, household_id, replies[state["pending_field"]])
        elif (state["expected"] or "").startswith("doc_"):
            turn = say(api, household_id, "हाँ")
        else:
            pytest.fail(f"Stuck at {state}: {turn['reply']}")
    assert turn["state"]["household"]["stage"] == "CONFIRM", turn["reply"]

    application = turn["state"]["applications"][0]
    assert application["scheme_id"] == "up_nirashrit_mahila"
    assert application["fill_accuracy"] == 1.0
    assert application["frames"] > 5
    frame = api.get(f"/api/applications/{application['id']}/frames/{application['frames'] - 1}")
    assert frame.status_code == 200 and frame.headers["content-type"] == "image/jpeg"

    refused = api.post(f"/api/applications/{application['id']}/submit")
    assert refused.status_code == 403

    turn = say(api, household_id, "हाँ, भेज दो")
    assert turn["state"]["applications"][0]["reference"].startswith("MOCK-")

    pdf = api.get(f"/api/applications/{application['id']}/pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"

    status = api.get(f"/portal/api/status/{turn['state']['applications'][0]['reference']}")
    assert status.json()["status"] == "submitted"

    api.post("/api/demo/advance", json={"days": 12})
    resumed = api.post(f"/api/households/{household_id}/session").json()
    assert "12 दिन से जाँच में" in resumed["reply"]["hi"]

    api.post("/api/demo/advance", json={"days": 20})
    final = api.get(f"/api/households/{household_id}").json()
    assert final["applications"][0]["status"] == "first_instalment"
    assert final["received_annual_inr"] == 12000
    assert {"under_verification", "approved", "first_instalment"} <= {e["status"] for e in final["applications"][0]["events"]}


def test_portal_says_it_is_not_a_government_site(api):
    page = api.get("/portal/up_nirashrit_mahila/form")
    assert "NOT A GOVERNMENT SITE" in page.text
    assert "name='bank_account'" in page.text
