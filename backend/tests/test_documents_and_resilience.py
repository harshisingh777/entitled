"""Document reading with UniOCR (server and on-device), the model bundle, and how the API behaves under strain."""
import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config, jobs, ocr, tools
from app.main import app
from app.uniocr import bundle

BACKEND = Path(__file__).resolve().parents[1]
SAMPLES = BACKEND / "app" / "static" / "samples"
HINDI_CARD = BACKEND / "tests" / "data" / "ration_card_hi.jpg"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def household(client):
    return client.post("/api/households", json={}).json()["household"]["id"]


def facts(client, household_id):
    return {f["key"]: f["value"] for f in client.get(f"/api/households/{household_id}").json()["facts"]}


def upload(client, household_id, name, data, mime="image/jpeg"):
    response = client.post(f"/api/households/{household_id}/ocr", files={"file": (name, data, mime)})
    assert response.status_code == 200, response.text
    return response.json()


# Reading on the server

def test_server_reads_a_hindi_ration_card(client, household):
    body = upload(client, household, "ration_card_hi.jpg", HINDI_CARD.read_bytes())
    assert body["extracted"]["doc_type"] == "ration_card"
    assert body["extracted"]["engine"] == "uniocr"
    known = facts(client, household)
    # Read in Hindi, written out in Latin letters for the English site and forms.
    assert known["name"] == "Sunita Devi"
    assert known["guardian_name"] == "Ram Prasad"
    assert known["address"] == "Gram Sareni"
    assert known["district"] == "Raybareli"
    assert known["bpl_card"] is True  # अंत्योदय (Antyodaya) is the poorest-household card.


def test_server_keeps_names_exactly_as_printed(client, household):
    # UniOCR's dictionary repair would turn Kamla into Kamala, so it stays off for documents.
    body = upload(client, household, "ration_card.jpg", (SAMPLES / "ration_card.jpg").read_bytes())
    assert facts(client, household)["name"] == "Kamla Devi"
    assert body["extracted"]["fields"]["address"] == "Village Bachhrawan"


def test_a_pdf_is_read(client, household):
    import pymupdf
    document = pymupdf.open()
    page = document.new_page(width=1100 * 0.75, height=680 * 0.75)
    page.insert_image(page.rect, filename=str(SAMPLES / "aadhaar.jpg"))
    body = upload(client, household, "aadhaar.pdf", document.tobytes(), "application/pdf")
    assert body["extracted"]["doc_type"] == "aadhaar"
    assert facts(client, household)["aadhaar_last4"] == "4821"


def test_a_locked_pdf_gets_a_clear_answer(client, household):
    import pymupdf
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "Aadhaar")
    locked = document.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="1234", owner_pw="owner")
    body = upload(client, household, "e-aadhaar.pdf", locked, "application/pdf")
    assert body["extracted"]["doc_type"] is None
    assert "password" in body["reply"]["en"]


def test_a_file_that_is_not_a_document_gets_a_clear_answer(client, household):
    body = upload(client, household, "notes.txt", b"just some text", "text/plain")
    assert body["extracted"]["doc_type"] is None
    assert "JPG, PNG or PDF" in body["reply"]["en"]


def test_a_sideways_phone_photo_is_turned_upright(client, household):
    from PIL import Image
    upright = Image.open(SAMPLES / "passbook.jpg")
    exif = Image.Exif()
    exif[0x0112] = 6  # Orientation: the camera was held sideways, so the stored pixels are rotated.
    stored = io.BytesIO()
    upright.rotate(90, expand=True).save(stored, "JPEG", exif=exif.tobytes())
    body = upload(client, household, "photo.jpg", stored.getvalue())
    assert body["extracted"]["fields"]["ifsc"] == "DEMO0001234"


# Reading on the person's phone

def test_text_read_on_the_phone_fills_the_profile(client, household):
    rows = ["AADHAAR SPECIMEN", "Name: Kamla Devi", "Date of Birth: 15/03/1968", "Number: XXXX XXXX 4821"]
    response = client.post(f"/api/households/{household}/ocr/text", json={"rows": rows})
    body = response.json()
    assert body["extracted"]["doc_type"] == "aadhaar"
    assert body["extracted"]["engine"] == "uniocr_device"
    assert "never left your phone" in body["reply"]["en"]
    known = facts(client, household)
    assert known["aadhaar_last4"] == "4821" and known["doc_aadhaar"] is True and known["name"] == "Kamla Devi"


def test_an_unmasked_aadhaar_from_a_phone_is_still_cut_to_four_digits(client, household):
    rows = ["AADHAAR", "Name: Kamla Devi", "9999 8888 4821"]
    response = client.post(f"/api/households/{household}/ocr/text", json={"rows": rows})
    assert "9999" not in response.text and "8888" not in response.text
    assert facts(client, household)["aadhaar_last4"] == "4821"


def test_text_the_phone_could_not_make_sense_of_asks_for_the_photo(client, household):
    before = client.get(f"/api/households/{household}").json()
    response = client.post(f"/api/households/{household}/ocr/text", json={"rows": ["RTRTH TS", "fTII: RTYR"]})
    assert response.json() == {"needs_image": True}
    after = client.get(f"/api/households/{household}").json()
    assert after["messages"] == before["messages"] and after["facts"] == before["facts"]


def test_text_from_a_phone_is_bounded(client, household):
    response = client.post(f"/api/households/{household}/ocr/text", json={"rows": ["x"] * 201})
    assert response.status_code == 422


def test_parse_rows_reads_hindi_labels():
    parsed = ocr.parse_rows(["राशन कार्ड", "कार्ड का प्रकार: एपीएल", "नाम: सुनीता देवी", "पिता का नाम: राम प्रसाद", "जिला: रायबरेली"])
    assert parsed["doc_type"] == "ration_card"
    assert parsed["fields"] == {"guardian_name": "Ram Prasad", "name": "Sunita Devi", "district": "Raybareli"}
    assert parsed["facts"] == {"bpl_card": False}


def test_a_passbook_account_number_is_never_taken_for_aadhaar():
    parsed = ocr.parse_rows(["BANK PASSBOOK", "Account No: 100200300412", "IFSC: DEMO0001234"])
    assert parsed["doc_type"] == "bank_passbook" and "aadhaar_last4" not in parsed["fields"]


# The model bundle

def _bundle(tmp_path: Path, tamper: bool = False) -> Path:
    model = b"onnx model bytes"
    manifest = {"files": {name: {"bytes": len(model), "sha256": hashlib.sha256(model).hexdigest()} for name in bundle.MODELS.values()}}
    path = tmp_path / "bundle.bin"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        for name in bundle.MODELS.values():
            archive.writestr(name, model + (b"!" if tamper else b""))
    return path


def test_the_real_bundle_matches_its_manifest(tmp_path):
    settings = bundle.model_paths(config.UNIOCR_BUNDLE, tmp_path)
    assert set(settings) == {"Det.model_path", "Rec.model_path", "Cls.model_path"}
    assert all(Path(path).exists() for path in settings.values())


def test_a_tampered_bundle_is_refused(tmp_path):
    with pytest.raises(bundle.BundleError):
        bundle.model_paths(_bundle(tmp_path, tamper=True), tmp_path / "out")


def test_a_damaged_unpacked_model_is_replaced(tmp_path):
    out = tmp_path / "out"
    settings = bundle.model_paths(_bundle(tmp_path), out)
    Path(settings["Det.model_path"]).write_bytes(b"half-written")
    bundle.model_paths(_bundle(tmp_path), out)
    assert Path(settings["Det.model_path"]).read_bytes() == b"onnx model bytes"


# Under strain

def test_a_full_heavy_slot_answers_busy_with_retry_after(client, household, monkeypatch):
    monkeypatch.setattr(jobs, "QUEUE_SECONDS", 0.1)
    with jobs.heavy():
        response = client.post(f"/api/households/{household}/ocr", files={"file": ("a.jpg", (SAMPLES / "aadhaar.jpg").read_bytes(), "image/jpeg")})
    assert response.status_code == 503
    assert response.json()["code"] == "busy"
    assert response.headers["retry-after"]


def test_a_busy_form_filler_is_explained_not_reported_as_a_failure(client, household, monkeypatch):
    def busy(*_):
        raise jobs.Busy()
    monkeypatch.setattr(tools, "fill_form", busy)
    for key, value in {"name": "Kamla Devi", "guardian_name": "Ramesh Kumar", "dob": "15/03/1968", "address": "Village",
                       "district": "Raebareli", "aadhaar_last4": "4821", "bank_account": "100200300412", "ifsc": "DEMO0001234",
                       "mobile": "9876543210", "annual_income": "40000"}.items():
        client.patch(f"/api/households/{household}/facts/{key}", json={"value": value})
    client.post(f"/api/households/{household}/chat", json={"text": "I am a 58 year old widow in Raebareli with a BPL card"})
    for doc in ("aadhaar", "ration_card", "bank_passbook", "death_certificate", "income_certificate"):
        client.post(f"/api/households/{household}/documents/{doc}", json={"have": True})
    reply = client.post(f"/api/households/{household}/form", json={"scheme_id": "up_nirashrit_mahila"}).json()["reply"]["en"]
    assert "busy" in reply and "failed" not in reply


def test_an_unexpected_error_still_answers_in_words(monkeypatch):
    def broken(*_):
        raise RuntimeError("database fell over")
    monkeypatch.setattr("app.views.operator_dashboard", broken)
    with TestClient(app, raise_server_exceptions=False) as quiet:
        response = quiet.get("/api/operator/dashboard")
    assert response.status_code == 500
    assert response.json() == {"code": "server_error", "en": "Something went wrong on the server. Please try again."}
    assert "database fell over" not in response.text


def test_every_api_response_carries_a_request_id(client):
    response = client.get("/api/config", headers={"x-request-id": "abc123"})
    assert response.headers["x-request-id"] == "abc123"
    assert client.get("/api/health").json() == {"status": "ok"}


def test_a_missing_household_is_a_404_the_page_can_recognise(client):
    response = client.post("/api/households/doesnotexist/form", json={"scheme_id": "up_nirashrit_mahila"})
    assert response.status_code == 404


@pytest.mark.parametrize("given, expected", [
    ("postgres://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
    ("postgresql://u:p@host/db?sslmode=require", "postgresql+psycopg://u:p@host/db?sslmode=require"),
    ("postgresql+psycopg://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
    ("sqlite:///x.db", "sqlite:///x.db"),
])
def test_database_urls_from_hosts_use_the_installed_driver(given, expected):
    assert config.database_url(given) == expected


@pytest.mark.parametrize("hindi, latin", [
    ("कमला देवी", "Kamla Devi"), ("राम प्रसाद", "Ram Prasad"), ("सुनीता कुमारी", "Sunita Kumari"), ("श्याम लाल", "Shyam Lal"),
    ("गुड़िया", "Gudiya"), ("प्रयागराज", "Prayagraj"), ("कृष्ण", "Krishna"), ("ग्राम सरेनी, जिला रायबरेली", "Gram Sareni, Jila Raybareli"),
    ("१५/०३/१९६८", "15/03/1968"), ("Kamla Devi", "Kamla Devi"),
])
def test_hindi_details_are_written_in_latin_letters(hindi, latin):
    from app.translit import to_latin
    assert to_latin(hindi) == latin
