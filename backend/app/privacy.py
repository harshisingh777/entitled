"""PII masking for anything stored in the action log or shown in summaries."""
import re

_SENSITIVE_KEYS = {"bank_account", "mobile", "aadhaar", "aadhaar_number"}
# Record ids are opaque and can happen to contain long digit runs. Masking them would break the log's links.
_IDENTIFIER_KEYS = {"application", "reference", "household"}
_LONG_DIGITS = re.compile(r"(?<![\dA-Za-z])(\d[\d ]{7,}\d)(?![\dA-Za-z])")


def mask_digits(value: str) -> str:
    digits = re.sub(r"\D", "", str(value))
    return f"XXXX{digits[-4:]}" if len(digits) > 4 else "XXXX"


def _mask_text(text: str) -> str:
    return _LONG_DIGITS.sub(lambda m: mask_digits(m.group(1)), text)


def mask_pii(value):
    if isinstance(value, dict):
        masked = {}
        for key, item in value.items():
            if key in _IDENTIFIER_KEYS:
                masked[key] = item
            elif key in _SENSITIVE_KEYS and item:
                masked[key] = mask_digits(item)
            else:
                masked[key] = mask_pii(item)
        return masked
    if isinstance(value, (list, tuple)):
        return [mask_pii(v) for v in value]
    if isinstance(value, str):
        return _mask_text(value)
    return value
