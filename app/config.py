import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

(BASE_DIR / "instance").mkdir(exist_ok=True)

DEFAULT_SECRET = "dev-only-change-me"


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY") or DEFAULT_SECRET
    TIMEZONE = os.environ.get("TIMEZONE", "Asia/Kolkata")
    # Checking in normally needs a location (see app/attendance.py) - set to 0 in a LOCAL .env only
    # (kohal, 2026-10-16: "just in dev") to skip that while testing on a machine/emulator where location is
    # awkward to grant. .env is gitignored and never deployed, so this can't reach prod by accident; prod's
    # own .env never sets it, so it stays required there regardless of what's merged.
    REQUIRE_ATTENDANCE_LOCATION = os.environ.get("REQUIRE_ATTENDANCE_LOCATION", "1") != "0"

    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or (
        f"sqlite:///{BASE_DIR / 'instance' / 'leads.db'}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024  # room for a handful of site-survey photos in one upload
    UPLOAD_DIR = BASE_DIR / "instance" / "uploads"
