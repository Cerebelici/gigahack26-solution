import logging
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]

# Real environment variables win over .env, so tests can point at their own database.
load_dotenv(BACKEND_DIR / ".env")

logger = logging.getLogger(__name__)

DEFAULT_DATABASE_URL = "postgresql://localhost:5432/gigahack"
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", BACKEND_DIR.parent / "uploads"))

JWT_ALGORITHM = "HS256"
JWT_TTL_HOURS = float(os.getenv("JWT_TTL_HOURS", "24"))
JWT_SECRET = os.getenv("JWT_SECRET", "")
if not JWT_SECRET:
    JWT_SECRET = secrets.token_urlsafe(32)
    logger.warning("JWT_SECRET is not set; using a random secret, so tokens stop working after a restart.")


def database_url() -> str:
    url = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    # A bare postgresql:// URL selects psycopg2 in SQLAlchemy; this project uses psycopg 3.
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url.removeprefix(prefix)
    return url
