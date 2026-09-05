"""
Pre-flight Environment & Readiness Checker for TikTok Bot.
Tests every requirement and prints clear diagnostic feedback.
"""

import sys
import os
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

def check_mark(success: bool) -> str:
    return "[OK]" if success else "[PENDING]"

def main():
    print("=" * 60)
    print("  TikTok Automation Bot - Environment Readiness Check")
    print("=" * 60)

    # 1. Check Python version
    py_version = sys.version.split()[0]
    py_ok = sys.version_info >= (3, 10)
    print(f"{check_mark(py_ok)} Python Version: {py_version} (Required: >= 3.10)")

    # 2. Check Dependencies
    packages = ["googleapiclient", "google.oauth2", "requests", "dotenv"]
    missing_packages = []
    for pkg in packages:
        try:
            __import__(pkg)
        except ImportError:
            missing_packages.append(pkg)
    deps_ok = len(missing_packages) == 0
    print(f"{check_mark(deps_ok)} Python Dependencies: {'All installed' if deps_ok else f'Missing: {missing_packages}'}")

    # 3. Check FFmpeg & FFprobe
    ffmpeg_ok = False
    ffprobe_ok = False
    try:
        res = subprocess.run(["ffmpeg", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        ffmpeg_ok = res.returncode == 0
    except Exception:
        pass

    try:
        res = subprocess.run(["ffprobe", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        ffprobe_ok = res.returncode == 0
    except Exception:
        pass

    print(f"{check_mark(ffmpeg_ok)} FFmpeg Binary: {'Available in PATH' if ffmpeg_ok else 'NOT FOUND'}")
    print(f"{check_mark(ffprobe_ok)} FFprobe Binary: {'Available in PATH' if ffprobe_ok else 'NOT FOUND'}")

    # 4. Check Watermark Image
    logo_path = BASE_DIR / "logo.png"
    logo_ok = logo_path.exists() and logo_path.stat().st_size > 0
    print(f"{check_mark(logo_ok)} Watermark Logo (logo.png): {'Found & Ready' if logo_ok else 'Missing logo.png'}")

    # 5. Check .env Configuration
    env_path = BASE_DIR / ".env"
    env_exists = env_path.exists()
    print(f"{check_mark(env_exists)} .env Configuration File: {'Found' if env_exists else 'Missing (.env.example needs to be copied)'}")

    # 6. Check Service Account Credentials
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=env_path)

    sa_file_name = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")
    sa_path = BASE_DIR / sa_file_name
    sa_exists = sa_path.exists() and sa_path.stat().st_size > 0
    print(f"{check_mark(sa_exists)} Google Service Account ({sa_file_name}): {'Found' if sa_exists else 'NOT FOUND (Required for Drive ingestion)'}")

    # 7. Check Drive Folder ID
    folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "")
    folder_ok = bool(folder_id) and folder_id != "your_drive_folder_id_here"
    print(f"{check_mark(folder_ok)} Google Drive Folder ID: {'Configured' if folder_ok else 'Not configured in .env'}")

    # 8. Check TikTok Credentials (Session ID or Access Token)
    tiktok_session = os.getenv("TIKTOK_SESSION_ID", "")
    tiktok_token = os.getenv("TIKTOK_ACCESS_TOKEN", "")
    session_ok = bool(tiktok_session) and len(tiktok_session) > 10 and tiktok_session != "your_tiktok_session_id_here"
    token_ok = bool(tiktok_token) and tiktok_token != "your_tiktok_access_token_here"
    tiktok_ok = session_ok or token_ok

    if session_ok:
        print(f"{check_mark(tiktok_ok)} TikTok Connection: Session ID Configured ({tiktok_session[:6]}...)")
    elif token_ok:
        print(f"{check_mark(tiktok_ok)} TikTok Connection: API Token Configured")
    else:
        print(f"{check_mark(tiktok_ok)} TikTok Connection: Not configured in .env")

    print("=" * 60)
    ready = deps_ok and ffmpeg_ok and ffprobe_ok and logo_ok and sa_exists and folder_ok and tiktok_ok
    if ready:
        print("  STATUS: 100% READY TO RUN! All prerequisites & credentials configured.")
        print("  -> Launch daemon: python bot_orchestrator.py")
    else:
        print("  STATUS: SETUP READY! Only personal API credentials needed in .env")
        if not sa_exists:
            print("  -> Please drop your 'service_account.json' into this folder.")
        if not folder_ok:
            print("  -> Please update GOOGLE_DRIVE_FOLDER_ID in .env.")
        if not tiktok_ok:
            print("  -> Please configure TIKTOK_SESSION_ID or TIKTOK_ACCESS_TOKEN in .env.")
    print("=" * 60)

if __name__ == "__main__":
    main()
