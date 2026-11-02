"""Document reading. Sarvam Vision when a key is set, on-device RapidOCR otherwise.

The image is only ever held in memory, so there is nothing to delete after extraction.
Aadhaar numbers are reduced to their last four digits before they leave this module.
"""
import io
import json
import os
import re
import subprocess
import sys
import threading
import time
import zipfile

import httpx

from . import config

# Reading and the browser agent are the two jobs that need real memory. They run one at a time, each in a
# process that ends with the job, so a small server gets everything back and the model never stays loaded.
heavy_job = threading.Lock()
READ_TIMEOUT_SECONDS = 110


def _rapidocr_rows(data: bytes) -> list[str]:
    with heavy_job:
        process = subprocess.run([sys.executable, "-m", "app.ocr"], input=data, capture_output=True,
                                 cwd=str(config.BACKEND), timeout=READ_TIMEOUT_SECONDS, env=_read_env())
    if process.returncode != 0:
        raise RuntimeError(process.stderr.decode("utf-8", "replace")[-600:])
    return json.loads(process.stdout.decode("utf-8"))


def _read_env() -> dict:
    if not config.OCR_LOW_MEMORY:
        return dict(os.environ)
    # Libraries start one thread per core they can see, which on a shared host is far more than this server's share.
    return {**os.environ, "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "MALLOC_ARENA_MAX": "1"}


def _read_in_this_process(data: bytes) -> list[str]:
    from rapidocr_onnxruntime import RapidOCR
    settings = {}
    if config.OCR_LOW_MEMORY:
        import cv2
        cv2.setNumThreads(1)
        settings = {"intra_op_num_threads": 1, "inter_op_num_threads": 1, "use_cls": False, "rec_batch_num": 1,
                    "det_limit_side_len": 736, "det_limit_type": "max"}
    result, _ = RapidOCR(**settings)(data)
    if not result:
        return []
    boxes = []
    for box, text, _score in result:
        ys = [p[1] for p in box]
        boxes.append({"top": min(ys), "bottom": max(ys), "left": min(p[0] for p in box), "text": text})
    boxes.sort(key=lambda b: (b["top"], b["left"]))
    rows: list[list[dict]] = []
    for item in boxes:
        centre = (item["top"] + item["bottom"]) / 2
        if rows and rows[-1][0]["top"] <= centre <= rows[-1][0]["bottom"]:
            rows[-1].append(item)
        else:
            rows.append([item])
    return [" ".join(b["text"] for b in sorted(row, key=lambda b: b["left"])) for row in rows]


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
        return _rapidocr_rows(data), "rapidocr"
    except (RuntimeError, subprocess.TimeoutExpired) as exc:  # The person is asked for another photo instead.
        print(f"Document reading failed: {type(exc).__name__}: {exc}"[:800], file=sys.stderr)
        return [], "rapidocr"


_LABELS = {
    "name": r"(?:applicant name|account holder|holder name|card holder|head of family|name)",
    "guardian_name": r"(?:husband(?:'s)? name|father(?:'s)? name|w/o|d/o|s/o|husband|father)",
    "dob": r"(?:date of birth|d\.?o\.?b\.?|birth)",
    "address": r"(?:address|village)",
    "district": r"(?:district|dist\.?)",
    "card_type": r"(?:card type|category|type)",
}


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
    if "ifsc" in lowered or "passbook" in lowered:
        return "bank_passbook"
    if "ration" in lowered:
        return "ration_card"
    if "aadhaar" in lowered or "aadhar" in lowered or re.search(r"\b\d{4}\s\d{4}\s\d{4}\b", text):
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

    aadhaar = re.search(r"\b(\d{4})\s?(\d{4})\s?(\d{4})\b", text)
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
        if "BPL" in card or "ANTYODAYA" in card or "AAY" in card:
            facts["bpl_card"] = True
        elif "APL" in card:
            facts["bpl_card"] = False
    if doc_type == "bank_passbook":
        facts["has_bank_account"] = True
    return {"doc_type": doc_type, "fields": fields, "facts": facts}


def read_document(data: bytes, filename: str = "document.jpg") -> dict:
    rows, engine = read_rows(data, filename)
    parsed = parse_rows(rows)
    parsed["engine"] = engine
    return parsed


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(_read_in_this_process(sys.stdin.buffer.read()), ensure_ascii=False))
