"""The human confirmation gate. Enforced here in code, never left to a prompt.

A token is an HMAC over the application id and a hash of its exact fields. Editing
any field changes the hash, so every earlier confirmation stops working.
"""
import base64
import hashlib
import hmac
import json
import time

from . import config


class GateRefused(Exception):
    def __init__(self, code: str, hi: str, en: str):
        super().__init__(code)
        self.code, self.hi, self.en = code, hi, en


def fields_hash(scheme_id: str, fields: dict, documents: list) -> str:
    canonical = json.dumps({"s": scheme_id, "f": fields, "d": sorted(documents)}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _sign(payload: str) -> str:
    return hmac.new(config.signing_secret(), payload.encode(), hashlib.sha256).hexdigest()


def mint(application_id: str, digest: str, actor: str) -> str:
    expires = int(time.time()) + config.CONFIRMATION_TTL_SECONDS
    payload = f"{application_id}|{digest}|{expires}|{actor}"
    return base64.urlsafe_b64encode(f"{payload}|{_sign(payload)}".encode()).decode()


def verify(token: str | None, application_id: str, digest: str) -> str:
    """Returns who confirmed, or raises GateRefused."""
    if not token:
        raise GateRefused(
            "missing_confirmation",
            "पुष्टि के बिना आवेदन नहीं भेजा जा सकता। पहले सारांश सुनकर हाँ कहिए।",
            "This application cannot be sent without confirmation. Hear the summary and say yes first.",
        )
    try:
        decoded = base64.urlsafe_b64decode(token.encode()).decode()
        app_id, signed_digest, expires, actor, signature = decoded.rsplit("|", 4)
    except (ValueError, UnicodeDecodeError) as exc:
        raise GateRefused("malformed_token", "पुष्टि मान्य नहीं है।", "That confirmation is not valid.") from exc
    if not hmac.compare_digest(signature, _sign(f"{app_id}|{signed_digest}|{expires}|{actor}")):
        raise GateRefused("bad_signature", "पुष्टि मान्य नहीं है।", "That confirmation is not valid.")
    if app_id != application_id:
        raise GateRefused("wrong_application", "यह पुष्टि किसी दूसरे आवेदन की है।", "That confirmation belongs to another application.")
    if signed_digest != digest:
        raise GateRefused("fields_changed", "जानकारी बदल गई है, दोबारा पुष्टि चाहिए।", "The details changed, so confirmation is needed again.")
    if int(expires) < time.time():
        raise GateRefused("expired", "पुष्टि का समय निकल गया, दोबारा पुष्टि कीजिए।", "The confirmation expired. Please confirm again.")
    return actor
