"""Document reading. Sarvam Vision when a key is set, otherwise UniOCR, our own offline engine, on this server.

The image is only ever held in memory, so there is nothing to delete after extraction.
Aadhaar numbers are reduced to their last four digits before they leave this module.
"""
import io
import json
import os
import re
import subprocess
import sys
import time
import zipfile

import httpx

from . import config, jobs, translit

LOCAL_ENGINE = "uniocr"
READ_TIMEOUT_SECONDS = 110
# Phone photos arrive at 4000 px and more. Labels and numbers read just as well at this size, in a fraction of the memory.
MAX_SIDE = 1600
# On a 512 MB server a Hindi read at 1280 px peaked at 466 MB for the whole container. At 960 px every sample and
# the Hindi card still read correctly. Phones read at 1600 px on the device, so this only shapes the fallback.
LOW_MEMORY_MAX_SIDE = 960
PDF_PAGES = 2


class UnreadableFile(ValueError):
    """The upload is not something we can read, such as a locked PDF. The person gets told why."""

    def __init__(self, en: str):
        super().__init__(en)
        self.en = en


def _local_rows(data: bytes) -> list[str]:
    # Reading runs in a process that ends with the job, so a small server gets every byte of the model back.
    with jobs.heavy():
        process = subprocess.run([sys.executable, "-m", "app.ocr"], input=data, capture_output=True,
                                 cwd=str(config.BACKEND), timeout=READ_TIMEOUT_SECONDS, env=_read_env())
    if process.returncode == 3:
        raise UnreadableFile(process.stderr.decode("utf-8", "replace").strip().splitlines()[-1])
    if process.returncode != 0:
        raise RuntimeError(process.stderr.decode("utf-8", "replace")[-600:])
    return json.loads(process.stdout.decode("utf-8"))


def _read_env() -> dict:
    if not config.OCR_LOW_MEMORY:
        return dict(os.environ)
    # Libraries start one thread per core they can see, which on a shared host is far more than this server's share.
    return {**os.environ, "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "MALLOC_ARENA_MAX": "1"}


def engine_settings(low_memory: bool) -> dict:
    # Lower detection thresholds than UniOCR's defaults find Hindi lines the detector otherwise skips. The 180-degree
    # classifier is off: it flips Devanagari lines (their top stroke reads as upside down), and photos are already
    # turned upright from their EXIF data. With it on, a Hindi ration card loses its name and address lines.
    settings = {"Global.log_level": "error", "Det.thresh": 0.2, "Det.box_thresh": 0.3, "Global.use_cls": False}
    if low_memory:
        settings.update({
            "EngineConfig.onnxruntime.intra_op_num_threads": 1, "EngineConfig.onnxruntime.inter_op_num_threads": 1,
            "Rec.rec_batch_num": 1, "Det.limit_side_len": LOW_MEMORY_MAX_SIDE,
        })
    return settings


def _pages(data: bytes, low_memory: bool):
    """Turns an upload into upright, reasonably sized RGB images: a photo, or the first pages of a PDF."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    limit = LOW_MEMORY_MAX_SIDE if low_memory else MAX_SIDE
    if data[:5] == b"%PDF-":
        import pymupdf
        try:
            document = pymupdf.open(stream=data, filetype="pdf")
        except Exception as exc:
            raise UnreadableFile("This PDF could not be opened. Please upload a photo of the document instead.") from exc
        if document.needs_pass:
            raise UnreadableFile("This PDF is locked with a password. Please upload a photo, or a PDF without a password.")
        for page in list(document)[:PDF_PAGES]:
            zoom = min(200 / 72, limit / max(page.rect.width, page.rect.height))
            pixels = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
            yield Image.frombytes("RGB", (pixels.width, pixels.height), pixels.samples)
        return
    try:
        image = Image.open(io.BytesIO(data))
        image.draft("RGB", (limit, limit))  # JPEGs decode straight at a smaller size, which saves most of the memory.
        image = ImageOps.exif_transpose(image).convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise UnreadableFile("This file is not a photo or PDF I can read. Please upload a JPG, PNG or PDF.") from exc
    image.thumbnail((limit, limit))
    yield image


def _read_in_this_process(data: bytes) -> list[str]:
    from .uniocr import bundle, engine

    low_memory = config.OCR_LOW_MEMORY
    if low_memory:
        import cv2
        cv2.setNumThreads(1)
    models = bundle.model_paths(config.UNIOCR_BUNDLE, config.DATA_DIR / "models" / "uniocr")
    engine.configure({**engine_settings(low_memory), **models})
    rows = []
    for page in _pages(data, low_memory):
        # repair=False: UniOCR's dictionary repair is for notes, and on an ID it would rewrite names (Kamla -> Kamala).
        text, _ = engine._extract(page, repair=False)
        rows += [line.strip() for line in text.splitlines() if line.strip()]
    return rows


def _sarvam_rows(data: bytes, filename: str) -> list[str]:
    headers = {"api-subscription-key": config.SARVAM_API_KEY}
    base = f"{config.SARVAM_BASE_URL}/doc-ai/v1/job"
    with httpx.Client(timeout=30) as client:
        created = client.post(f"{base}/parse", headers=headers, files={"file": (filename, data)},
                              data={"language": "hi-IN", "output_format": "md"})
        created.raise_for_status()
        job_id = created.json()["job_id"]
        for _ in range(30):
            state = client.get(f"{base}/{job_id}/status", headers=headers).json()["status"]
            if state in ("completed", "partially_completed"):
                break
            if state in ("failed", "rejected"):
                raise RuntimeError(f"Sarvam Vision job {state}")
            time.sleep(1)
        else:
            raise TimeoutError("Sarvam Vision job timed out")
        url = client.get(f"{base}/{job_id}/download-url", headers=headers).json()["url"]
        archive = zipfile.ZipFile(io.BytesIO(client.get(url).content))
    markdown = next(n for n in archive.namelist() if n.endswith(".md"))
    return [line.strip(" |#*") for line in archive.read(markdown).decode("utf-8").splitlines() if line.strip()]


def read_rows(data: bytes, filename: str = "document.jpg") -> tuple[list[str], str]:
    if config.SARVAM_API_KEY:
        try:
            return _sarvam_rows(data, filename), "sarvam_vision"
        except Exception:  # A network or quota failure must not stop the flow, the local reader takes over.
            pass
    try:
        return _local_rows(data), LOCAL_ENGINE
    except (RuntimeError, subprocess.TimeoutExpired) as exc:  # The person is asked for another photo instead.
        print(f"Document reading failed: {type(exc).__name__}: {exc}"[:800], file=sys.stderr)
        return [], LOCAL_ENGINE


# English and Hindi labels. UP ration cards are printed in Hindi, and Aadhaar cards carry both.
_LABELS = {
    "name": r"(?:applicant name|account holder|holder name|card holder|head of family|name|नाम)",
    "guardian_name": r"(?:husband(?:'s)? name|father(?:'s)? name|w/o|d/o|s/o|husband|father|पति का नाम|पिता का नाम|पति|पिता)",
    "dob": r"(?:date of birth|d\.?o\.?b\.?|birth|जन्म तिथि)",
    "address": r"(?:address|village|पता)",
    "district": r"(?:district|dist\.?|जिला|ज़िला)",
    "card_type": r"(?:card type|category|type|कार्ड का प्रकार|श्रेणी)",
}
# A phone that read the card itself sends the Aadhaar number already cut to XXXX XXXX 1234.
_AADHAAR = r"\b(\d{4}|X{4})\s?(\d{4}|X{4})\s?(\d{4})\b"


def _value_after(rows: list[str], label: str) -> str | None:
    # OCR often swallows spaces, so 'Account No' may arrive as 'AccountNo' and 'Kamla Devi' as 'KamlaDevi'.
    flexible = label.replace(" ", r"\s*")
    pattern = re.compile(rf"(?<![a-z]){flexible}\s*[:\-.]?\s*(.+)", re.IGNORECASE)
    for row in rows:
        match = pattern.search(row)
        if match and match.group(1).strip(" :-."):
            return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", match.group(1).strip(" :-"))
    return None


def detect_type(text: str) -> str | None:
    lowered = text.lower()
    if "ifsc" in lowered or "passbook" in lowered or "पासबुक" in text:
        return "bank_passbook"
    if "ration" in lowered or "राशन" in text:
        return "ration_card"
    if "aadhaar" in lowered or "aadhar" in lowered or "आधार" in text or re.search(r"\b(?:\d{4}|X{4})\s(?:\d{4}|X{4})\s\d{4}\b", text):
        return "aadhaar"
    return None


def parse_rows(rows: list[str]) -> dict:
    """Layout rules: a label and its value sit on the same visual row."""
    text = "\n".join(rows)
    doc_type = detect_type(text)
    fields: dict[str, str] = {}

    guardian = _value_after(rows, _LABELS["guardian_name"])
    if guardian:
        fields["guardian_name"] = guardian
    name_rows = [r for r in rows if not re.search(_LABELS["guardian_name"] + r"|bank\s*name", r, re.IGNORECASE)]
    name = _value_after(name_rows, _LABELS["name"])
    if name:
        fields["name"] = name

    dob = re.search(r"\b(\d{2})[/\-.](\d{2})[/\-.](\d{4})\b", text)
    if dob and doc_type != "bank_passbook":
        fields["dob"] = f"{dob.group(1)}/{dob.group(2)}/{dob.group(3)}"

    if doc_type != "bank_passbook":
        address = _value_after(rows, _LABELS["address"])
        if address:
            fields["address"] = address
    district = _value_after(rows, _LABELS["district"])
    if district:
        fields["district"] = district

    aadhaar = re.search(_AADHAAR, text)
    if aadhaar and doc_type == "aadhaar":
        fields["aadhaar_last4"] = aadhaar.group(3)

    if doc_type == "bank_passbook":
        ifsc = re.search(r"\b[A-Z]{4}0[A-Z0-9]{6}\b", text.upper())
        if ifsc:
            fields["ifsc"] = ifsc.group()
        for row in rows:
            account = re.search(r"(?:account|a/c)\D*(\d[\d ]{7,20}\d)", row, re.IGNORECASE)
            digits = re.sub(r"\D", "", account.group(1)) if account else ""
            if 9 <= len(digits) <= 18:
                fields["bank_account"] = digits
                break

    facts: dict[str, object] = {}
    if doc_type == "ration_card":
        card = (_value_after(rows, _LABELS["card_type"]) or "").upper()
        if any(word in card for word in ("BPL", "ANTYODAYA", "AAY", "बीपीएल", "अंत्योदय")):
            facts["bpl_card"] = True
        elif "APL" in card or "एपीएल" in card:
            facts["bpl_card"] = False
    if doc_type == "bank_passbook":
        facts["has_bank_account"] = True
    # The site and the forms are in English, so details from a Hindi document are written in Latin letters.
    fields = {key: translit.to_latin(value) for key, value in fields.items()}
    return {"doc_type": doc_type, "fields": fields, "facts": facts}


def read_document(data: bytes, filename: str = "document.jpg") -> dict:
    rows, engine = read_rows(data, filename)
    parsed = parse_rows(rows)
    parsed["engine"] = engine
    return parsed


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    try:
        found = _read_in_this_process(sys.stdin.buffer.read())
    except UnreadableFile as unreadable:
        print(unreadable.en, file=sys.stderr)
        raise SystemExit(3)
    print(json.dumps(found, ensure_ascii=False))
