"""Settings, read from the environment and an optional .env at the repo root."""
import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
SCHEMES_DIR = ROOT / "schemes"
STATIC_DIR = BACKEND / "app" / "static"


def _load_dotenv() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()
DATA_DIR = Path(os.environ.get("ENTITLED_DATA_DIR", BACKEND / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{(DATA_DIR / 'entitled.db').as_posix()}")
PORT = int(os.environ.get("BACKEND_PORT", "8000"))
INTERNAL_BASE_URL = os.environ.get("INTERNAL_BASE_URL", f"http://127.0.0.1:{PORT}")
POLL_SECONDS = int(os.environ.get("STATUS_POLL_SECONDS", "60"))
CONFIRMATION_TTL_SECONDS = 600

SARVAM_API_KEY = os.environ.get("SARVAM_API_KEY", "")
SARVAM_BASE_URL = os.environ.get("SARVAM_BASE_URL", "https://api.sarvam.ai")
SARVAM_STT_MODEL = os.environ.get("SARVAM_STT_MODEL", "saaras:v3")
SARVAM_TTS_MODEL = os.environ.get("SARVAM_TTS_MODEL", "bulbul:v3")
SARVAM_TTS_SPEAKER = os.environ.get("SARVAM_TTS_SPEAKER", "priya")

BHASHINI_USER_ID = os.environ.get("BHASHINI_USER_ID", "")
BHASHINI_API_KEY = os.environ.get("BHASHINI_API_KEY", "")
BHASHINI_URL = os.environ.get("BHASHINI_URL", "https://dhruva-api.bhashini.gov.in/services/inference/pipeline")

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.sarvam.ai/v1")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "") or SARVAM_API_KEY
LLM_MODEL = os.environ.get("LLM_MODEL", "sarvam-105b")
LLM_FALLBACK_BASE_URL = os.environ.get("LLM_FALLBACK_BASE_URL", "")
LLM_FALLBACK_API_KEY = os.environ.get("LLM_FALLBACK_API_KEY", "")
LLM_FALLBACK_MODEL = os.environ.get("LLM_FALLBACK_MODEL", "")

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM = os.environ.get("TWILIO_FROM", "")


def signing_secret() -> bytes:
    """Key for confirmation tokens. Generated once and kept outside the repo."""
    configured = os.environ.get("CONFIRMATION_SECRET")
    if configured:
        return configured.encode()
    path = DATA_DIR / ".confirmation_secret"
    if not path.exists():
        path.write_text(secrets.token_hex(32), encoding="utf-8")
    return path.read_text(encoding="utf-8").strip().encode()
