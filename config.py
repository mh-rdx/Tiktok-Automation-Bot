"""
Configuration module.
Loads, validates, and exposes environment variables and operational constants.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Base directory of the project
BASE_DIR = Path(__file__).resolve().parent
env_path = BASE_DIR / ".env"
load_dotenv(dotenv_path=env_path)


def _get_env(key: str, default: str | None = None, required: bool = True) -> str:
    val = os.getenv(key, default)
    if required and not val:
        print(f"[CONFIG WARNING] Missing environment variable: {key}")
        print(f"Please make sure {key} is set in your .env file.")
    return str(val) if val is not None else ""


# Google Drive Settings
SERVICE_ACCOUNT_FILE = Path(_get_env("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json", required=False))
if not SERVICE_ACCOUNT_FILE.is_absolute():
    SERVICE_ACCOUNT_FILE = BASE_DIR / SERVICE_ACCOUNT_FILE

DRIVE_FOLDER_ID = _get_env("GOOGLE_DRIVE_FOLDER_ID", required=False)

# TikTok API & Session Settings
TIKTOK_SESSION_ID = _get_env("TIKTOK_SESSION_ID", required=False)
TIKTOK_COOKIES_JSON = _get_env("TIKTOK_COOKIES_JSON", required=False)
TIKTOK_ACCESS_TOKEN = _get_env("TIKTOK_ACCESS_TOKEN", required=False)
TIKTOK_OPEN_ID = _get_env("TIKTOK_OPEN_ID", required=False)
DEFAULT_CAPTION = _get_env("DEFAULT_CAPTION", "Daily Reel! #fyp #trending", required=False)

# Video Processing Settings
WATERMARK_PATH = Path(_get_env("WATERMARK_PATH", "logo.png", required=False))
if not WATERMARK_PATH.is_absolute():
    WATERMARK_PATH = BASE_DIR / WATERMARK_PATH

WATERMARK_WIDTH_RATIO = float(os.getenv("WATERMARK_WIDTH_RATIO", "0.15"))
WATERMARK_PADDING = int(os.getenv("WATERMARK_PADDING", "10"))
ANTI_DUPLICATE_FILTER = os.getenv("ANTI_DUPLICATE_FILTER", "true").lower() in ("true", "1", "yes")

# Scheduling & Rate Limiting Settings
DAILY_LIMIT = int(os.getenv("DAILY_LIMIT", "5"))
POST_INTERVAL_SECONDS = int(os.getenv("POST_INTERVAL_SECONDS", "7200"))
JITTER_MIN_SECONDS = int(os.getenv("JITTER_MIN_SECONDS", "60"))
JITTER_MAX_SECONDS = int(os.getenv("JITTER_MAX_SECONDS", "600"))
EMPTY_QUEUE_SLEEP_SECONDS = int(os.getenv("EMPTY_QUEUE_SLEEP_SECONDS", "900"))

# Internal File Paths
TEMP_DIR = BASE_DIR / os.getenv("TEMP_DIR", "temp")
STATE_FILE = BASE_DIR / "state.json"

# Automatically create local scratch directory if missing
TEMP_DIR.mkdir(parents=True, exist_ok=True)
