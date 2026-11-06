import os
import sys
import tempfile
from pathlib import Path

TEST_DATA = tempfile.mkdtemp(prefix="entitled-tests-")
os.environ["ENTITLED_DATA_DIR"] = TEST_DATA
# TEST_DATABASE_URL runs the suite against PostgreSQL instead, such as a throwaway one in Docker.
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{Path(TEST_DATA, 'test.db').as_posix()}"
# Tests never touch paid or external services, whatever a developer's .env holds.
for key in ("SARVAM_API_KEY", "BHASHINI_API_KEY", "BHASHINI_USER_ID", "LLM_API_KEY", "LLM_FALLBACK_API_KEY", "TWILIO_ACCOUNT_SID"):
    os.environ[key] = ""

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
