"""Loads the UniOCR model bundle, uniocr_mobile.bin: the same file the browser reads on the phone.

The bundle is a zip of ONNX models plus a manifest of their sha256 sums. RapidOCR needs files on disk, so the
models are unpacked once into the data folder, and each one is checked against the manifest before it is used.
"""
import hashlib
import json
import os
import zipfile
from pathlib import Path

MODELS = {"Det": "PP-OCRv6_det_small.onnx", "Rec": "PP-OCRv6_rec_small.onnx", "Cls": "ch_ppocr_mobile_v2.0_cls_mobile.onnx"}


class BundleError(RuntimeError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def model_paths(bundle: Path, out: Path) -> dict[str, str]:
    """RapidOCR settings that point each stage at a verified model from the bundle."""
    if not bundle.exists():
        raise BundleError(f"UniOCR bundle not found at {bundle}")
    out.mkdir(parents=True, exist_ok=True)
    settings = {}
    with zipfile.ZipFile(bundle) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        for stage, name in MODELS.items():
            expected = manifest["files"][name]["sha256"]
            target, stamp = out / name, out / f"{name}.sha256"
            # The stamp is written only after a verified unpack, so a half-written file is never trusted.
            fresh = target.exists() and stamp.exists() and stamp.read_text().strip() == expected \
                and target.stat().st_size == manifest["files"][name]["bytes"]
            if not fresh:
                data = archive.read(name)
                if _sha256(data) != expected:
                    raise BundleError(f"{name} in the UniOCR bundle does not match its checksum")
                partial = target.with_name(f"{name}.{os.getpid()}.part")
                partial.write_bytes(data)
                os.replace(partial, target)
                stamp.write_text(expected)
            settings[f"{stage}.model_path"] = str(target)
    return settings
