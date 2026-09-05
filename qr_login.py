"""
TikTok QR Code Login Manager.
Handles headless QR-code generation, phone scan confirmation, session extraction,
and automatic synchronization with Railway variables.
"""

import os
import time
import json
import logging
import threading
from pathlib import Path
from typing import Optional, Dict, Any

from playwright.sync_api import sync_playwright
import requests

import config

logger = logging.getLogger(__name__)

SESSION_FILE = config.BASE_DIR / "tiktok_session.json"


class TikTokQRLoginManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(TikTokQRLoginManager, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.state_lock = threading.Lock()
        self.status = "idle"  # idle | generating | waiting_for_scan | authenticated | expired | error
        self.qr_image_data: Optional[str] = None
        self.error_message: Optional[str] = None
        self.authenticated_user: Optional[str] = None
        self.worker_thread: Optional[threading.Thread] = None

    def get_status(self) -> Dict[str, Any]:
        with self.state_lock:
            return {
                "status": self.status,
                "qr_image": self.qr_image_data,
                "error": self.error_message,
                "user": self.authenticated_user,
                "has_saved_session": SESSION_FILE.exists()
            }

    def start_login_session(self) -> Dict[str, Any]:
        with self.state_lock:
            if self.status in ["generating", "waiting_for_scan"]:
                return self.get_status()
            self.status = "generating"
            self.qr_image_data = None
            self.error_message = None
            self.authenticated_user = None

        self.worker_thread = threading.Thread(target=self._run_qr_flow, daemon=True)
        self.worker_thread.start()

        # Wait up to 12 seconds for the QR code to be rendered
        for _ in range(24):
            time.sleep(0.5)
            with self.state_lock:
                if self.qr_image_data or self.status in ["error", "authenticated"]:
                    break

        return self.get_status()

    def _run_qr_flow(self):
        logger.info("Starting headless Playwright session for TikTok QR login...")
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-infobars",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                        "--window-size=1280,800"
                    ]
                )
                context = browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                    locale="en-US"
                )
                context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                    Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
                    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
                    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                    window.chrome = { runtime: {} };
                """)

                page = context.new_page()
                page.goto("https://www.tiktok.com/login/qrcode", wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(3000)

                # Extract base64 image data
                found_qr = None
                for _ in range(20):
                    imgs = page.locator('img').all()
                    for img in imgs:
                        src = img.get_attribute('src') or ''
                        if src.startswith('data:image'):
                            found_qr = src
                            break
                    if found_qr:
                        break
                    page.wait_for_timeout(500)

                if not found_qr:
                    qr_pic = config.TEMP_DIR / "login_qr.png"
                    page.screenshot(path=str(qr_pic))
                    found_qr = "/api/screenshot/qr"

                with self.state_lock:
                    self.qr_image_data = found_qr
                    self.status = "waiting_for_scan"
                logger.info("TikTok QR code extracted successfully. Waiting for phone scan...")

                # Wait up to 3 minutes for phone scan & authorization
                start_time = time.time()
                while time.time() - start_time < 180:
                    page.wait_for_timeout(2000)
                    url = page.url
                    # Once logged in, TikTok leaves /login
                    if "login" not in url.lower():
                        logger.info(f"Scan confirmed! Logged into TikTok: {url}")
                        page.wait_for_timeout(3000)

                        # Save Playwright storage state
                        context.storage_state(path=str(SESSION_FILE))
                        logger.info(f"Saved session storage to: {SESSION_FILE}")

                        # Extract cookies
                        cookies = context.cookies()
                        cookies_json = json.dumps(cookies)

                        # Try to navigate to studio
                        try:
                            page.goto("https://www.tiktok.com/tiktokstudio", wait_until="domcontentloaded", timeout=30000)
                            page.wait_for_timeout(2000)
                        except Exception:
                            pass

                        with self.state_lock:
                            self.status = "authenticated"
                            self.authenticated_user = "TikTok User"

                        # Persist to Railway environment variables if token available
                        self._sync_to_railway(cookies_json)

                        browser.close()
                        return

                with self.state_lock:
                    self.status = "expired"
                    self.error_message = "QR code scan timed out (180s). Please try again."
                browser.close()

        except Exception as e:
            logger.error(f"Error during QR login flow: {e}", exc_info=True)
            with self.state_lock:
                self.status = "error"
                self.error_message = str(e)

    def _sync_to_railway(self, cookies_json: str):
        """Attempts to update TIKTOK_COOKIES_JSON on Railway service."""
        token = os.getenv("RAILWAY_TOKEN", "b54e69bd-7e2c-4412-840f-ccd24f2893bb")
        project_id = os.getenv("RAILWAY_PROJECT_ID", "31fb51f1-7b77-4c3a-9e66-4e9c788a7d67")
        env_id = os.getenv("RAILWAY_ENVIRONMENT_ID", "8d2b0b13-a952-47e0-8e22-6cc917d20652")
        service_id = os.getenv("RAILWAY_SERVICE_ID", "ce456392-5f96-4328-b3a5-c408d4dc74c4")

        if not token or not service_id:
            logger.info("Railway variables sync skipped (missing token or service_id).")
            return

        query = """
        mutation VariableUpsert($input: VariableUpsertInput!) {
            variableUpsert(input: $input)
        }
        """
        variables = {
            "input": {
                "projectId": project_id,
                "environmentId": env_id,
                "serviceId": service_id,
                "name": "TIKTOK_COOKIES_JSON",
                "value": cookies_json
            }
        }
        try:
            resp = requests.post(
                "https://backboard.railway.app/graphql/v2",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"query": query, "variables": variables},
                timeout=10
            )
            if resp.status_code == 200 and "errors" not in resp.json():
                logger.info("Successfully updated TIKTOK_COOKIES_JSON on Railway project!")
            else:
                logger.warning(f"Railway variable sync response: {resp.text}")
        except Exception as err:
            logger.warning(f"Could not auto-sync to Railway API: {err}")
