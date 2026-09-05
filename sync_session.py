"""
1-Click Local TikTok Session Exporter & Server Synchronizer.
Run this script locally on your PC to instantly connect your TikTok account to Railway!
Supports Google Login, Phone, Email, Facebook, or existing browser session.
"""

import os
import sys
import time
import json
from pathlib import Path
import requests

BASE_DIR = Path(__file__).resolve().parent
SESSION_FILE = BASE_DIR / "tiktok_session.json"
DEFAULT_SERVER_URL = "https://worker-production-4386.up.railway.app"

SERVER_URL = os.getenv("SERVER_URL", DEFAULT_SERVER_URL).rstrip("/")


def upload_session_to_server(session_data: dict) -> bool:
    print(f"\n📡 Uploading TikTok session to Railway server ({SERVER_URL})...")
    upload_url = f"{SERVER_URL}/api/session/upload"
    try:
        resp = requests.post(upload_url, json=session_data, timeout=30)
        if resp.status_code == 200 and resp.json().get("success"):
            print("=" * 60)
            print("🎉 SUCCESS! TikTok account connected to your 24/7 bot on Railway!")
            print(f"Server response: {resp.json().get('message')}")
            print("=" * 60)
            return True
        else:
            print(f"❌ Server rejected session: {resp.text}")
            return False
    except Exception as e:
        print(f"❌ Connection error to {SERVER_URL}: {e}")
        return False


def export_via_browser():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("❌ Playwright is required. Installing playwright...")
        os.system(f"{sys.executable} -m pip install playwright")
        os.system(f"{sys.executable} -m playwright install chromium")
        from playwright.sync_api import sync_playwright

    print("\n🚀 Launching local browser on your PC...")
    print("👉 If you are not already logged in, please log in using ANY method:")
    print("   (Continue with Google, QR Code, Email, Phone, etc.)")
    print("👉 Once logged in to TikTok Studio, this script will automatically capture your session!\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        page.goto("https://www.tiktok.com/tiktokstudio", wait_until="domcontentloaded")

        print("⏳ Waiting for TikTok login (waiting up to 180 seconds)...")
        start = time.time()
        authenticated = False

        while time.time() - start < 180:
            time.sleep(2)
            cur_url = page.url.lower()
            # If in studio and not on login page
            if "tiktokstudio" in cur_url and "login" not in cur_url:
                # Check for profile or upload container
                try:
                    page.wait_for_timeout(2000)
                    authenticated = True
                    break
                except Exception:
                    pass

        if not authenticated:
            print("❌ Login timed out. Please run the script again and complete login.")
            browser.close()
            return False

        print("\n✅ Detected active TikTok Studio login!")
        # Export storage state
        context.storage_state(path=str(SESSION_FILE))
        print(f"💾 Saved local session to: {SESSION_FILE}")

        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            session_data = json.load(f)

        browser.close()
        return upload_session_to_server(session_data)


def main():
    print("=" * 65)
    print("  TIME PASS | TikTok 1-Click Railway Synchronizer")
    print("=" * 65)
    print(f"Target Server: {SERVER_URL}")

    # Check if local session file already exists
    if SESSION_FILE.exists():
        print(f"\n📁 Found existing local session file: {SESSION_FILE}")
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "cookies" in data and len(data["cookies"]) > 0:
                print(f"📦 Loaded {len(data['cookies'])} cookies from existing session.")
                success = upload_session_to_server(data)
                if success:
                    return
                print("⚠️ Existing session was invalid or expired. Opening browser to refresh...")
        except Exception as e:
            print(f"Could not load existing file: {e}")

    export_via_browser()


if __name__ == "__main__":
    main()
