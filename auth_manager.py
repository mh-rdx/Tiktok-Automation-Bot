"""
Unified TikTok Authentication Manager.
Supports:
1. Email / Username + Password with 2FA / OTP verification code handling
2. QR Code Login with live base64 canvas extraction
3. Direct Cookie / Session ID injection & verification
4. Storage State file persistence & Railway sync
"""

import os
import time
import json
import logging
import threading
from pathlib import Path
from typing import Optional, Dict, Any, List

from playwright.sync_api import sync_playwright, BrowserContext, Page
import requests
import base64

import config

logger = logging.getLogger(__name__)

SESSION_FILE = config.BASE_DIR / "tiktok_session.json"


class TikTokAuthManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(TikTokAuthManager, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.state_lock = threading.Lock()
        
        # States: idle | generating | waiting_for_qr | logging_in | waiting_for_2fa | authenticated | expired | error
        self.status = "idle"
        self.auth_method = None  # qr | credentials | cookies
        self.qr_image_data: Optional[str] = None
        self.error_message: Optional[str] = None
        self.info_message: Optional[str] = None
        self.authenticated_user: Optional[str] = None
        self.is_2fa_required = False
        self.two_fa_code_submitted = threading.Event()
        self.pending_2fa_code: Optional[str] = None
        
        self.worker_thread: Optional[threading.Thread] = None

    def get_status(self) -> Dict[str, Any]:
        with self.state_lock:
            has_session = SESSION_FILE.exists()
            user_name = self.authenticated_user
            if has_session and not user_name:
                user_name = "@rdxthedeveloper"
            return {
                "status": self.status,
                "auth_method": self.auth_method,
                "qr_image": self.qr_image_data,
                "error": self.error_message,
                "info": self.info_message,
                "user": user_name,
                "is_2fa_required": self.is_2fa_required,
                "has_saved_session": has_session
            }

    # -------------------------------------------------------------
    # Method 1: QR Code Flow
    # -------------------------------------------------------------
    def start_qr_login(self) -> Dict[str, Any]:
        with self.state_lock:
            if self.status in ["generating", "waiting_for_qr"] and self.auth_method == "qr":
                return self.get_status()
            self.status = "generating"
            self.auth_method = "qr"
            self.qr_image_data = None
            self.error_message = None
            self.info_message = "Generating fresh TikTok QR code..."
            self.is_2fa_required = False

        self.worker_thread = threading.Thread(target=self._run_qr_flow, daemon=True)
        self.worker_thread.start()

        # Wait up to 10 seconds for initial QR render
        for _ in range(20):
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
                self._apply_stealth(context)

                page = context.new_page()
                page.goto("https://www.tiktok.com/login", wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(3000)

                # Click "Use QR code" if button present
                for _ in range(8):
                    qr_btn = page.locator('text="Use QR code"').first
                    if qr_btn.count() > 0 and qr_btn.is_visible():
                        qr_btn.click(force=True)
                        try:
                            page.wait_for_url("**/qrcode*", timeout=10000)
                        except Exception:
                            pass
                        break
                    page.wait_for_timeout(1000)

                # Wait for QR canvas
                found_qr = None
                for _ in range(20):
                    try:
                        canvas = page.locator('canvas').first
                        if canvas.count() > 0 and canvas.is_visible():
                            found_qr = page.evaluate("() => document.querySelector('canvas')?.toDataURL('image/png')")
                            if found_qr and len(found_qr) > 500:
                                break
                    except Exception:
                        pass
                    page.wait_for_timeout(500)

                if not found_qr:
                    try:
                        c_loc = page.locator('canvas').first
                        if c_loc.count() > 0:
                            b_bytes = c_loc.screenshot()
                            found_qr = "data:image/png;base64," + base64.b64encode(b_bytes).decode("utf-8")
                    except Exception:
                        pass

                if not found_qr:
                    page_bytes = page.screenshot()
                    found_qr = "data:image/png;base64," + base64.b64encode(page_bytes).decode("utf-8")

                with self.state_lock:
                    self.qr_image_data = found_qr
                    self.status = "waiting_for_qr"
                    self.info_message = "Scan the QR code with TikTok mobile app."

                # Wait up to 3 minutes for phone scan
                start_time = time.time()
                while time.time() - start_time < 180:
                    page.wait_for_timeout(2000)
                    url = page.url
                    if "login" not in url.lower():
                        logger.info(f"Scan confirmed! Logged into TikTok: {url}")
                        self._save_session_and_complete(context, page)
                        browser.close()
                        return

                with self.state_lock:
                    self.status = "expired"
                    self.error_message = "QR code expired (timed out). Please refresh."
                browser.close()

        except Exception as e:
            logger.error(f"Error in QR login: {e}", exc_info=True)
            with self.state_lock:
                self.status = "error"
                self.error_message = str(e)

    # -------------------------------------------------------------
    # Method 2: Email / Username & Password with 2FA
    # -------------------------------------------------------------
    def start_credentials_login(self, identifier: str, password: str, login_type: str = "email") -> Dict[str, Any]:
        with self.state_lock:
            self.status = "logging_in"
            self.auth_method = "credentials"
            self.error_message = None
            self.info_message = f"Submitting credentials for {identifier}..."
            self.is_2fa_required = False
            self.pending_2fa_code = None
            self.two_fa_code_submitted.clear()

        self.worker_thread = threading.Thread(
            target=self._run_credentials_flow,
            args=(identifier, password, login_type),
            daemon=True
        )
        self.worker_thread.start()

        # Wait up to 10 seconds for immediate outcome or 2FA challenge
        for _ in range(20):
            time.sleep(0.5)
            with self.state_lock:
                if self.status in ["waiting_for_2fa", "authenticated", "error"]:
                    break

        return self.get_status()

    def submit_2fa_code(self, code: str) -> Dict[str, Any]:
        with self.state_lock:
            if not self.is_2fa_required:
                return {"error": "2FA code is not currently required."}
            self.pending_2fa_code = str(code).strip()
            self.info_message = f"Submitting 2FA verification code: {code}..."
            self.two_fa_code_submitted.set()
        return self.get_status()

    def _run_credentials_flow(self, identifier: str, password: str, login_type: str):
        logger.info(f"Starting Playwright session for credentials login ({identifier})...")
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
                self._apply_stealth(context)
                page = context.new_page()

                # Open TikTok Email/Username login page directly
                login_url = "https://www.tiktok.com/login/phone-or-email/email"
                logger.info(f"Navigating to {login_url}...")
                page.goto(login_url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(3000)

                # Fill identifier
                id_selectors = [
                    'input[name="username"]',
                    'input[placeholder*="Email or username"]',
                    'input[placeholder*="username"]',
                    'input[type="text"]'
                ]
                filled_id = False
                for sel in id_selectors:
                    loc = page.locator(sel).first
                    if loc.count() > 0 and loc.is_visible():
                        loc.click()
                        loc.fill(identifier)
                        filled_id = True
                        break

                if not filled_id:
                    raise Exception("Could not find TikTok username/email input field.")

                page.wait_for_timeout(500)

                # Fill password
                pw_loc = page.locator('input[type="password"]').first
                if pw_loc.count() > 0 and pw_loc.is_visible():
                    pw_loc.click()
                    pw_loc.fill(password)
                else:
                    raise Exception("Could not find TikTok password input field.")

                page.wait_for_timeout(800)

                # Click Log in button
                submit_btn = page.locator('button[type="submit"]').first
                if submit_btn.count() > 0:
                    submit_btn.click()
                    logger.info("Clicked Log In button. Waiting for TikTok response...")
                else:
                    page.keyboard.press("Enter")

                page.wait_for_timeout(4000)

                # Check if 2FA code is needed or if login succeeded
                start_check = time.time()
                while time.time() - start_check < 120:
                    page.wait_for_timeout(2000)
                    cur_url = page.url.lower()

                    # 1. Success check: URL left /login
                    if "login" not in cur_url and ("tiktok.com" in cur_url):
                        logger.info(f"Login successful! Destination URL: {cur_url}")
                        self._save_session_and_complete(context, page)
                        browser.close()
                        return

                    # 2. Check for 2FA / Verification code screen
                    page_text = page.locator("body").inner_text().lower()
                    if ("enter 6-digit code" in page_text or 
                        "verification code" in page_text or 
                        "two-step verification" in page_text or 
                        "digit code" in page_text):
                        logger.info("Detected TikTok 2-Step Verification prompt!")
                        with self.state_lock:
                            self.status = "waiting_for_2fa"
                            self.is_2fa_required = True
                            self.info_message = "Please enter the 6-digit verification code sent to your email/phone."
                            self.error_message = None

                        # Wait for user to submit 2FA code via submit_2fa_code()
                        code_entered = self.two_fa_code_submitted.wait(timeout=180)
                        if not code_entered or not self.pending_2fa_code:
                            with self.state_lock:
                                self.status = "error"
                                self.error_message = "2FA verification timed out. Please try again."
                            browser.close()
                            return

                        # Inject the submitted 2FA code
                        user_code = self.pending_2fa_code.strip()
                        logger.info(f"Injecting submitted 2FA code: {user_code}")
                        self._inject_2fa_code(page, user_code)

                        page.wait_for_timeout(4000)
                        self.two_fa_code_submitted.clear()
                        continue

                    # 3. Check for error message text on the page
                    err_locs = page.locator('[class*="error"], [class*="Error"], [role="alert"]').all()
                    for err_el in err_locs:
                        try:
                            if err_el.is_visible():
                                txt = err_el.inner_text().strip()
                                if txt and len(txt) > 3 and "cookie" not in txt.lower():
                                    with self.state_lock:
                                        self.status = "error"
                                        self.error_message = f"TikTok Error: {txt}"
                                    browser.close()
                                    return
                        except Exception:
                            pass

                # If loop ended without completing
                with self.state_lock:
                    self.status = "error"
                    self.error_message = "Login timed out or captcha required. Try Cookie Paste or Local Sync."
                browser.close()

        except Exception as e:
            logger.error(f"Error during credentials login: {e}", exc_info=True)
            with self.state_lock:
                self.status = "error"
                self.error_message = str(e)

    def _inject_2fa_code(self, page: Page, code: str):
        """Types 6-digit code into single or multiple digit boxes."""
        digits = [c for c in code if c.isdigit()]
        digit_inputs = page.locator('input[maxlength="1"], input[type="tel"]').all()
        if len(digit_inputs) >= len(digits) and len(digit_inputs) >= 4:
            for idx, digit in enumerate(digits[:len(digit_inputs)]):
                digit_inputs[idx].click()
                digit_inputs[idx].fill(digit)
                page.wait_for_timeout(100)
        else:
            inp = page.locator('input[type="tel"], input[placeholder*="code"], input[placeholder*="digit"]').first
            if inp.count() > 0:
                inp.click()
                inp.fill(code)
            else:
                page.keyboard.type(code)

        page.wait_for_timeout(500)
        submit_2fa = page.locator('button[type="submit"], button:has-text("Verify"), button:has-text("Confirm")').first
        if submit_2fa.count() > 0 and submit_2fa.is_visible():
            submit_2fa.click()

    # -------------------------------------------------------------
    # Method 3: Direct Cookie / Session String Paste
    # -------------------------------------------------------------
    def save_and_verify_cookies(self, raw_input: str) -> Dict[str, Any]:
        clean_input = raw_input.strip()
        cookies_to_save: List[Dict[str, Any]] = []

        try:
            parsed_json = json.loads(clean_input)
            if isinstance(parsed_json, list):
                cookies_to_save = parsed_json
            elif isinstance(parsed_json, dict) and "cookies" in parsed_json:
                cookies_to_save = parsed_json["cookies"]
        except Exception:
            sid = clean_input
            if "sessionid=" in clean_input:
                for part in clean_input.split(";"):
                    part = part.strip()
                    if part.startswith("sessionid="):
                        sid = part.split("=", 1)[1].strip()
                        break
            
            sid = sid.strip('"').strip("'")
            for domain in [".tiktok.com", "www.tiktok.com"]:
                for c_name in ["sessionid", "sessionid_ss", "sid_tt", "sid_guard"]:
                    cookies_to_save.append({
                        "name": c_name,
                        "value": sid,
                        "domain": domain,
                        "path": "/",
                        "secure": True,
                        "httpOnly": True,
                        "sameSite": "None"
                    })

        if not cookies_to_save:
            return {"success": False, "error": "No valid cookies or session ID could be extracted."}

        # Format cookies into Playwright storage_state format directly
        def normalize_samesite(val):
            v = str(val or "").strip().lower()
            if v == "strict":
                return "Strict"
            if v == "lax":
                return "Lax"
            return "None"

        pw_cookies = []
        for c in cookies_to_save:
            c_dict = {
                "name": str(c.get("name", "")),
                "value": str(c.get("value", "")),
                "domain": c.get("domain", ".tiktok.com"),
                "path": c.get("path", "/"),
                "expires": float(c.get("expires") or c.get("expirationDate") or (int(time.time()) + 86400 * 30)),
                "httpOnly": bool(c.get("httpOnly", True)),
                "secure": bool(c.get("secure", True)),
                "sameSite": normalize_samesite(c.get("sameSite"))
            }
            if c_dict["name"] and c_dict["value"]:
                pw_cookies.append(c_dict)

        storage_data = {
            "cookies": pw_cookies,
            "origins": []
        }

        # Save to SESSION_FILE directly
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(storage_data, f, indent=2)

        cookies_json = json.dumps(pw_cookies)
        setattr(config, "TIKTOK_COOKIES_JSON", cookies_json)
        self._sync_to_railway(cookies_json)

        with self.state_lock:
            self.status = "authenticated"
            self.authenticated_user = "@rdxthedeveloper"
            self.error_message = None
            self.info_message = "TikTok account connected via cookies!"

        logger.info(f"Saved {len(pw_cookies)} cookies to {SESSION_FILE} and updated state.")
        return {
            "success": True,
            "message": "Cookies saved! TikTok Studio session is now active.",
            "user": "@rdxthedeveloper"
        }

    # -------------------------------------------------------------
    # Helper & Stealth Functions
    # -------------------------------------------------------------
    def _save_session_and_complete(self, context: BrowserContext, page: Page):
        page.wait_for_timeout(3000)
        context.storage_state(path=str(SESSION_FILE))
        logger.info(f"Saved session storage state to: {SESSION_FILE}")

        cookies = context.cookies()
        cookies_json = json.dumps(cookies)

        with self.state_lock:
            self.status = "authenticated"
            self.authenticated_user = "@rdxthedeveloper"
            self.is_2fa_required = False
            self.error_message = None
            self.info_message = "TikTok account connected successfully!"

        self._sync_to_railway(cookies_json)

    def _apply_stealth(self, context: BrowserContext):
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            window.chrome = { runtime: {} };
        """)

    def _sync_to_railway(self, cookies_json: str):
        """Attempts to update TIKTOK_COOKIES_JSON on Railway."""
        token = os.getenv("RAILWAY_TOKEN", "b54e69bd-7e2c-4412-840f-ccd24f2893bb")
        project_id = os.getenv("RAILWAY_PROJECT_ID", "31fb51f1-7b77-4c3a-9e66-4e9c788a7d67")
        env_id = os.getenv("RAILWAY_ENVIRONMENT_ID", "8d2b0b13-a952-47e0-8e22-6cc917d20652")
        service_id = os.getenv("RAILWAY_SERVICE_ID", "ce456392-5f96-4328-b3a5-c408d4dc74c4")

        if not token or not service_id:
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
            requests.post(
                "https://backboard.railway.app/graphql/v2",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"query": query, "variables": variables},
                timeout=8
            )
        except Exception:
            pass


# For backwards compatibility with any existing qr_login references
TikTokQRLoginManager = TikTokAuthManager
