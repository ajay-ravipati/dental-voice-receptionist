"""Central settings but overridable via environment variables."""
import os

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

LIVE_MODEL = os.getenv("GEMINI_LIVE_MODEL", "gemini-3.8-live")
VOICE_NAME = os.getenv("GEMINI_VOICE", "Aoede")

# --- limits
MAX_CALL_SECONDS = _int("MAX_CALL_SECONDS", 240)
IDLE_TIMEOUT_SECONDS = _int("IDLE_TIMEOUT_SECONDS", 45)
MAX_CONCURRENT_CALLS = _int("MAX_CONCURRENT_CALLS", 3)
MAX_CALLS_PER_IP_PER_DAY = _int("MAX_CALLS_PER_IP_PER_DAY", 6)
MAX_TOOL_CALLS_PER_CALL = _int("MAX_TOOL_CALLS_PER_CALL", 25)

ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
TIMEZONE = "Asia/Kolkata"
