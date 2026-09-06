"""
Dual-Mode TikTok Upload Service.
Supports both:
1. Browser Session Upload via Playwright & TIKTOK_SESSION_ID (Direct TikTok Studio)
2. Official Content Posting API v2 via TIKTOK_ACCESS_TOKEN
"""

import time
import math
import logging
from pathlib import Path
from typing import Dict, Any, Optional
import requests
import json

import config

logger = logging.getLogger(__name__)

INIT_UPLOAD_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"
STATUS_CHECK_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"


class TikTokUploadError(Exception):
    """Custom exception for TikTok upload failures."""
    pass


class TikTokContentRestrictedError(TikTokUploadError):
    """Raised when TikTok Studio Content Check flags the video as restricted/unoriginal."""
    pass


class TikTokUploader:
    def __init__(self):
        self.session_id = getattr(config, "TIKTOK_SESSION_ID", None)
        self.access_token = getattr(config, "TIKTOK_ACCESS_TOKEN", None)
        self.chunk_size = 10 * 1024 * 1024  # 10MB chunk size for API v2

    def upload_via_playwright(self, video_path: Path, caption: Optional[str] = None) -> bool:
        """
        Uploads video to TikTok Studio directly using Playwright headless browser
        and the authenticated sessionid cookies.
        """
        from playwright.sync_api import sync_playwright

        post_caption = caption or config.DEFAULT_CAPTION
        logger.info(f"Starting TikTok Studio upload via Playwright for: {video_path.name}")
        logger.info(f"Caption: {post_caption[:60]}...")

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-infobars",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--window-size=1920,1080"
                ]
            )
            session_file = config.BASE_DIR / "tiktok_session.json"
            
            # If session_file does not exist on disk but TIKTOK_COOKIES_JSON is set, generate it
            if not session_file.exists() and hasattr(config, "TIKTOK_COOKIES_JSON") and config.TIKTOK_COOKIES_JSON.strip():
                try:
                    full_cookies = json.loads(config.TIKTOK_COOKIES_JSON.strip())
                    if isinstance(full_cookies, list):
                        pw_cookies = []
                        for c in full_cookies:
                            raw_ss = str(c.get("sameSite", "")).strip().lower()
                            if raw_ss == "strict":
                                clean_ss = "Strict"
                            elif raw_ss == "lax":
                                clean_ss = "Lax"
                            else:
                                clean_ss = "None"
                            exp = c.get("expirationDate") or c.get("expires") or (int(time.time()) + 86400 * 30)
                            pw_cookies.append({
                                "name": str(c.get("name", "")),
                                "value": str(c.get("value", "")),
                                "domain": c.get("domain", ".tiktok.com"),
                                "path": c.get("path", "/"),
                                "expires": float(exp),
                                "httpOnly": bool(c.get("httpOnly", True)),
                                "secure": bool(c.get("secure", True)),
                                "sameSite": clean_ss
                            })
                        with open(session_file, "w", encoding="utf-8") as sf:
                            json.dump({"cookies": pw_cookies, "origins": []}, sf, indent=2)
                        logger.info(f"Auto-generated {session_file.name} from TIKTOK_COOKIES_JSON with {len(pw_cookies)} cookies.")
                except Exception as ce:
                    logger.warning(f"Could not build session_file from TIKTOK_COOKIES_JSON: {ce}")

            ctx_params = {
                "viewport": {"width": 1920, "height": 1080},
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "locale": "en-US",
                "timezone_id": "America/New_York"
            }
            if session_file.exists():
                try:
                    # Sanitize any invalid sameSite values from browser cookie export
                    with open(session_file, "r", encoding="utf-8") as sf:
                        s_data = json.load(sf)
                    changed = False
                    for c in s_data.get("cookies", []):
                        raw_ss = str(c.get("sameSite", "")).strip().lower()
                        if raw_ss == "strict":
                            clean_ss = "Strict"
                        elif raw_ss == "lax":
                            clean_ss = "Lax"
                        else:
                            clean_ss = "None"
                        if c.get("sameSite") != clean_ss:
                            c["sameSite"] = clean_ss
                            changed = True
                    if changed:
                        with open(session_file, "w", encoding="utf-8") as sf:
                            json.dump(s_data, sf, indent=2)
                        logger.info("Sanitized sameSite cookie attributes in tiktok_session.json for Playwright.")

                    ctx_params["storage_state"] = str(session_file)
                    logger.info("Using saved authenticated browser storage state from tiktok_session.json")
                except Exception as se:
                    logger.warning(f"Could not load/sanitize storage_state: {se}")

            context = browser.new_context(**ctx_params)

            # Anti-bot detection mitigation script
            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                Object.defineProperty(navigator, 'platform', {
                    get: () => 'Win32'
                });
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['en-US', 'en']
                });
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5]
                });
                window.chrome = {
                    runtime: {},
                    loadTimes: function() {},
                    csi: function() {},
                    app: {}
                };
            """)

            # Only inject fallback cookies from env vars if session_file does not exist
            if not session_file.exists():
                cookies = []
                # 1. Check if full cookie suite JSON is provided
                if hasattr(config, "TIKTOK_COOKIES_JSON") and config.TIKTOK_COOKIES_JSON.strip():
                    try:
                        full_cookies = json.loads(config.TIKTOK_COOKIES_JSON.strip())
                        if isinstance(full_cookies, list):
                            for c in full_cookies:
                                c_dict = {
                                    "name": c.get("name"),
                                    "value": c.get("value"),
                                    "domain": c.get("domain", ".tiktok.com"),
                                    "path": c.get("path", "/"),
                                }
                                if "secure" in c:
                                    c_dict["secure"] = c["secure"]
                                if "httpOnly" in c:
                                    c_dict["httpOnly"] = c["httpOnly"]
                                if "sameSite" in c and c["sameSite"] in ["Strict", "Lax", "None"]:
                                    c_dict["sameSite"] = c["sameSite"]
                                cookies.append(c_dict)
                            logger.info(f"Loaded {len(cookies)} cookies from TIKTOK_COOKIES_JSON")
                    except Exception as c_err:
                        logger.warning(f"Could not parse TIKTOK_COOKIES_JSON: {c_err}")

                # 2. Inject session_id cookies across domains with secure attributes
                clean_sid = str(self.session_id or "").strip().strip('"').strip("'")
                if clean_sid:
                    for domain in [".tiktok.com", "www.tiktok.com"]:
                        for c_name in ["sessionid", "sessionid_ss", "sid_tt", "sid_guard"]:
                            if not any(c.get("name") == c_name and c.get("domain") == domain for c in cookies):
                                cookies.append({
                                    "name": c_name,
                                    "value": clean_sid,
                                    "domain": domain,
                                    "path": "/",
                                    "secure": True,
                                    "httpOnly": True,
                                    "sameSite": "None"
                                })

                if cookies:
                    context.add_cookies(cookies)
                    logger.info(f"Successfully injected {len(cookies)} TikTok session cookies into Playwright context.")
            else:
                logger.info("Using authenticated session_file storage_state without environment overrides.")

            page = context.new_page()

            try:
                # Direct navigation to creator studio upload with query params
                upload_url = "https://www.tiktok.com/tiktokstudio/upload?from=creator_center&tab=video"
                logger.info(f"Navigating to TikTok Studio Upload: {upload_url}")
                page.goto(upload_url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(6000)

                current_url = page.url
                logger.info(f"TikTok Page loaded. Current URL: {current_url}")

                # Check if session is valid
                if "login" in current_url.lower():
                    err_pic = config.TEMP_DIR / "tiktok_error.png"
                    try:
                        page.screenshot(path=str(err_pic))
                        logger.warning(f"Saved login redirect screenshot to {err_pic}")
                    except Exception:
                        pass
                    raise TikTokUploadError(
                        f"TikTok session rejected. Redirected to login: {current_url}. Please refresh your session cookies."
                    )

                # Save refreshed session state
                try:
                    context.storage_state(path=str(session_file))
                except Exception:
                    pass

                # Fallback check for + Upload button if not directly on upload dropzone
                file_input = page.locator('input[type="file"]').first
                if file_input.count() == 0:
                    logger.info("Dropzone not immediately visible, checking for Upload button...")
                    up_btn = page.locator('button:has-text("Upload"), a:has-text("Upload")').first
                    if up_btn.count() > 0:
                        up_btn.click()
                        page.wait_for_timeout(4000)
                    file_input = page.locator('input[type="file"]').first

                if file_input.count() == 0:
                    err_pic = config.TEMP_DIR / "tiktok_upload_err.png"
                    page.screenshot(path=str(err_pic))
                    raise TikTokUploadError(f"Could not locate file input on upload page. Screenshot saved to {err_pic}")

                logger.info(f"Injecting video file: {video_path.resolve()}")
                file_input.set_input_files(str(video_path.resolve()))

                logger.info("Video injected. Waiting for upload processing & editor to mount (10s)...")
                page.wait_for_timeout(10000)


                # Dismiss any initial onboarding or permission modals
                self._handle_active_modals(page)

                # Enter Caption
                caption_selector = '.public-DraftEditor-content, div[contenteditable="true"], .notranslate[contenteditable="true"]'
                logger.info("Locating caption editor...")
                try:
                    page.wait_for_selector(caption_selector, timeout=30000)
                    caption_el = page.locator(caption_selector).first
                    caption_el.click(force=True)
                    page.wait_for_timeout(500)

                    # Clear existing text
                    page.keyboard.press("Control+A")
                    page.keyboard.press("Backspace")
                    page.wait_for_timeout(500)

                    # Insert caption with emojis and hashtags
                    logger.info("Typing caption and viral hashtags into Draft.js editor...")
                    page.keyboard.insert_text(post_caption)
                    page.wait_for_timeout(1500)
                    page.keyboard.press("Escape")  # Dismiss hashtag suggestions dropdown
                    page.wait_for_timeout(500)
                except Exception as cap_err:
                    logger.warning(f"Could not fill caption via Draft.js ({cap_err}). Continuing with upload...")

                # Scroll to bottom so footer Post button is in DOM
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(1000)

                # Find real Publish/Post Button (strictly excluding sidebar navigation buttons)
                logger.info("Locating Publish/Post button...")
                post_btn = None
                for selector in [
                    'button.Button__root--type-primary:has-text("Post")',
                    'button:not([data-tt*="Sidebar"]):text-is("Post")',
                    'button:not([data-tt*="Sidebar"]):has-text("Post")',
                    'div.btn-post button',
                ]:
                    loc = page.locator(selector).first
                    if loc.count() > 0:
                        post_btn = loc
                        logger.info(f"Found post button using selector: '{selector}'")
                        break

                if not post_btn:
                    raise TikTokUploadError("Could not find 'Post' button on TikTok Studio.")

                # Wait until post button is enabled (supports 2-3 minute videos that take longer to process)
                logger.info("Waiting for video upload & server processing to complete (up to 6 mins)...")
                is_ready = False
                for attempt in range(120):  # 120 * 3s = 360 seconds (6 minutes)
                    # Regularly handle any active modals that pop up during processing
                    self._handle_active_modals(page)

                    try:
                        # Re-locate post button to avoid stale element references on React re-render
                        candidate_btn = page.locator(
                            'button.Button__root--type-primary:has-text("Post"), '
                            'button:not([data-tt*="Sidebar"]):text-is("Post"), '
                            'button:not([data-tt*="Sidebar"]):has-text("Post")'
                        ).first
                        if candidate_btn.count() > 0 and candidate_btn.is_enabled():
                            post_btn = candidate_btn
                            is_ready = True
                            logger.info("Post button is enabled and ready to publish!")
                            break
                    except Exception:
                        pass

                    if attempt % 5 == 0:
                        logger.info(f"Video still processing on TikTok servers... ({attempt * 3}s elapsed)")
                    page.wait_for_timeout(3000)

                if not is_ready:
                    raise TikTokUploadError("Video processing timed out on TikTok Studio after 6 minutes.")

                # Check if video was flagged with restrictions by TikTok Content Check
                if getattr(config, "SKIP_RESTRICTED_VIDEOS", True):
                    violation = self._detect_restriction_violation(page)
                    if violation:
                        self._discard_and_abort_restricted(page, browser, violation)

                # Ensure no blocking dialogs before clicking Post
                self._handle_active_modals(page)

                # Scroll into view and click
                post_btn.scroll_into_view_if_needed()
                page.wait_for_timeout(500)
                logger.info("Clicking Post button...")
                post_btn.click(force=True)

                # Wait for publish confirmation & actively handle any confirmation/advisory modals
                logger.info("Waiting for publish confirmation & handling any confirmation/advisory modals...")
                published = False
                for attempt in range(60):  # 60 * 2s = 120 seconds
                    page.wait_for_timeout(2000)

                    # Check if video was flagged with restrictions
                    if getattr(config, "SKIP_RESTRICTED_VIDEOS", True):
                        violation = self._detect_restriction_violation(page)
                        if violation:
                            self._discard_and_abort_restricted(page, browser, violation)

                    # 1. Handle any visible modal (confirmations like 'Post'/'Post anyway' or advisories)
                    modal_action_taken = self._handle_active_modals(page)
                    if modal_action_taken:
                        page.wait_for_timeout(2000)

                    # 2. Check for successful publish confirmation
                    url = page.url
                    content = page.content().lower()
                    if (
                        "/content" in url
                        or "/posts" in url
                        or "your video has been uploaded" in content
                        or "manage your posts" in content
                        or "post another video" in content
                        or "view post" in content
                        or "video published" in content
                        or "✓ video published" in content
                    ):
                        logger.info(f"TikTok post published successfully! Confirmation detected (URL: {url})")
                        published = True
                        break

                    # 3. If no modal is visible on screen and 12s+ elapsed, safely retry clicking Post button
                    if attempt in (6, 15, 25):
                        try:
                            # Verify no modal dialog is currently visible
                            has_modal = page.locator('div[role="dialog"]:visible, div.TUXModal:visible, div[class*="modal" i]:visible').count() > 0
                            if not has_modal:
                                re_post = page.locator(
                                    'button.Button__root--type-primary:has-text("Post"), '
                                    'button:not([data-tt*="Sidebar"]):text-is("Post"), '
                                    'button:not([data-tt*="Sidebar"]):has-text("Post")'
                                ).first
                                if re_post.count() > 0 and re_post.is_visible() and re_post.is_enabled():
                                    logger.info("No modal visible and post still pending. Retrying main 'Post' button click...")
                                    re_post.click(force=True)
                        except Exception:
                            pass

                diag_path = config.TEMP_DIR / "tiktok_post_result.png"
                page.screenshot(path=str(diag_path))
                logger.info(f"Diagnostic screenshot saved to {diag_path}")

                if published:
                    page.wait_for_timeout(3000)
                    success_path = config.TEMP_DIR / "tiktok_published_verified.png"
                    page.screenshot(path=str(success_path))
                    logger.info(f"Verified publish screenshot saved to {success_path}")
                    browser.close()
                    return True
                else:
                    browser.close()
                    raise TikTokUploadError("Post button was clicked but TikTok did not confirm publish within timeout.")

            except TikTokContentRestrictedError:
                browser.close()
                raise
            except Exception as e:
                err_pic = config.TEMP_DIR / "tiktok_error.png"
                try:
                    page.screenshot(path=str(err_pic))
                    logger.warning(f"Saved error screenshot to {err_pic}")
                except Exception:
                    pass
                browser.close()
                raise TikTokUploadError(f"Playwright TikTok upload failed: {e}")

    def _handle_active_modals(self, page) -> bool:
        """
        Scans for genuinely VISIBLE modal dialogs on TikTok Studio and handles them:
        1. Confirmation dialogs ('Post anyway', 'Post now', 'Post', 'Continue to post', 'Publish anyway') -> Clicks proceed button!
        2. Advisory / Details dialogs ('Content may be restricted', 'Got it', 'Understood') -> Clicks close 'X' or acknowledgment!
        3. Danger dialogs ('Cancel upload') -> Clicks 'No'!
        4. Exit dialogs ('Unsaved changes') -> Clicks 'Cancel' to stay on page!
        Returns True if a modal was handled.
        """
        handled = False
        try:
            # 1. Safety check: 'Sure you want to cancel your upload?' -> click 'No'
            no_btn = page.locator('button:text-is("No"), button:has-text("No")').first
            if no_btn.count() > 0 and no_btn.is_visible():
                logger.info("Dismissed unexpected cancel upload dialog by clicking 'No'.")
                no_btn.click(force=True)
                page.wait_for_timeout(500)
                return True

            # 2. Safety check: 'Unsaved changes / Exit' -> click 'Cancel'
            exit_btn = page.locator('button:has-text("Exit")').first
            if exit_btn.count() > 0 and exit_btn.is_visible():
                cancel_btn = page.locator('button:text-is("Cancel")').first
                if cancel_btn.count() > 0 and cancel_btn.is_visible():
                    logger.info("Dismissed exit dialog by clicking 'Cancel'.")
                    cancel_btn.click(force=True)
                    page.wait_for_timeout(500)
                    return True

            # 3. Check for any genuinely VISIBLE modal/dialog container
            modal_locators = page.locator(
                'div[role="dialog"], div.TUXModal, div[class*="modal" i]:not([class*="mask"]):not([class*="backdrop"])'
            )
            modal_count = modal_locators.count()

            for i in range(modal_count):
                modal = modal_locators.nth(i)
                if not modal.is_visible():
                    continue

                modal_text = modal.inner_text().strip().replace("\n", " ")
                logger.info(f"Active visible modal detected on page: '{modal_text[:90]}...'")

                # If modal asks "Sure you want to cancel your upload?", click "No" to keep uploading!
                if "cancel your upload" in modal_text.lower():
                    no_btn = modal.locator('button:text-is("No"), button:has-text("No")').first
                    if no_btn.count() > 0 and no_btn.is_visible():
                        logger.info("Dismissing 'Sure you want to cancel your upload?' modal by clicking 'No'.")
                        no_btn.click(force=True)
                        page.wait_for_timeout(1000)
                        return True

                # A. Check for confirmation / proceed buttons inside this modal
                # In TikTok Studio, confirmation dialogs have a button with "Post", "Post anyway", "Post now", "Continue to post", "Publish"
                for btn_text in [
                    "Post anyway",
                    "Post now",
                    "Continue to post",
                    "Publish anyway",
                    "Confirm",
                    "Post",
                ]:
                    try:
                        action_btn = modal.locator(f'button:text-is("{btn_text}"), button:has-text("{btn_text}")').first
                        if action_btn.count() > 0 and action_btn.is_visible():
                            txt = action_btn.inner_text().strip().lower()
                            if txt not in ["cancel", "discard", "replace video"]:
                                logger.info(f"Clicking confirmation button inside modal: '{action_btn.inner_text().strip()}'")
                                action_btn.click(force=True)
                                page.wait_for_timeout(1500)
                                return True
                    except Exception:
                        pass

                # Also check for primary button by class inside this modal
                try:
                    primary_btn = modal.locator('button.Button__root--type-primary, button[class*="primary" i]').first
                    if primary_btn.count() > 0 and primary_btn.is_visible():
                        p_txt = primary_btn.inner_text().strip().lower()
                        if p_txt not in ["cancel", "discard", "replace video"]:
                            logger.info(f"Clicking primary button inside modal: '{primary_btn.inner_text().strip()}'")
                            primary_btn.click(force=True)
                            page.wait_for_timeout(1500)
                            return True
                except Exception:
                    pass

                # B. Check for acknowledgment buttons (Got it, Understood, I understand, Acknowledge)
                for ack_text in ["Got it", "Understood", "I understand", "Acknowledge", "Turn on"]:
                    try:
                        ack_btn = modal.locator(f'button:text-is("{ack_text}"), button:has-text("{ack_text}")').first
                        if ack_btn.count() > 0 and ack_btn.is_visible():
                            logger.info(f"Clicking acknowledgment button inside modal: '{ack_text}'")
                            ack_btn.click(force=True)
                            page.wait_for_timeout(1000)
                            return True
                    except Exception:
                        pass

                # C. If it's an advisory/detail modal (e.g. "Content may be restricted" detail view with "Replace video"),
                # close it using the 'X' close button inside the modal!
                close_btn = modal.locator('button[aria-label*="close" i], button:has(svg)').first
                if close_btn.count() > 0 and close_btn.is_visible():
                    logger.info("Closing advisory modal via 'X' button inside modal dialog.")
                    close_btn.click(force=True)
                    page.wait_for_timeout(1000)
                    return True

                # If no close button found inside visible modal, press Escape specifically for this modal
                logger.info("Pressing Escape to close visible modal.")
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)
                return True

            # 4. Standalone benign buttons that might appear outside formal dialogs
            for btn_text in ["Got it", "Turn on"]:
                try:
                    b = page.locator(f'button:text-is("{btn_text}")').first
                    if b.count() > 0 and b.is_visible():
                        logger.info(f"Dismissing benign button: '{btn_text}'")
                        b.click(force=True)
                        page.wait_for_timeout(500)
                        return True
                except Exception:
                    pass

        except Exception as e:
            logger.debug(f"Notice in _handle_active_modals: {e}")

        return handled

    _dismiss_advisory_and_check_modals = _handle_active_modals

    def _detect_restriction_violation(self, page) -> Optional[str]:
        """
        Checks if TikTok Studio flagged the video with content restrictions:
        - 'Content may be restricted'
        - 'Violation reason'
        - 'Unoriginal, low-quality'
        - 'Ineligible for recommendation'
        Returns reason string if restricted, otherwise None.
        """
        try:
            # 1. Check open modal
            dialogs = page.locator('div[role="dialog"], div.TUXModal, div[class*="modal" i]')
            for i in range(dialogs.count()):
                d = dialogs.nth(i)
                if d.is_visible():
                    text = d.inner_text().lower()
                    if (
                        "content may be restricted" in text
                        or "violation reason" in text
                        or "unoriginal" in text
                        or "ineligible for recommendation" in text
                    ):
                        return "Modal: Content may be restricted (Unoriginal / Low-quality content)"

            # 2. Check the Checks section on page DOM
            checks_section = page.locator('div:has-text("Checks"), div:has-text("Content check lite")').first
            if checks_section.count() > 0:
                c_text = checks_section.inner_text().lower()
                if "content may be restricted" in c_text or "ineligible for recommendation" in c_text:
                    return "Checks section: Content may be restricted / Ineligible for recommendation"

            # 3. Fallback check across page content
            content = page.content().lower()
            if "content may be restricted" in content and "checks" in content:
                return "Page check: Content may be restricted"

        except Exception as e:
            logger.debug(f"Notice in _detect_restriction_violation: {e}")

        return None

    def _discard_and_abort_restricted(self, page, browser, reason: str):
        """
        Discards the draft on TikTok Studio, closes browser, and raises TikTokContentRestrictedError.
        """
        logger.warning("=" * 65)
        logger.warning(f"🚨 TIKTOK CONTENT RESTRICTION DETECTED: {reason}")
        logger.warning("SKIP_RESTRICTED_VIDEOS is active: Aborting upload and requesting deletion from Google Drive...")
        logger.warning("=" * 65)

        restr_pic = config.TEMP_DIR / "tiktok_restricted_detected.png"
        try:
            page.screenshot(path=str(restr_pic))
            logger.info(f"Saved restriction diagnostic screenshot to {restr_pic}")
        except Exception:
            pass

        # Discard the draft on TikTok Studio
        try:
            discard_btn = page.locator('button:text-is("Discard"), button:has-text("Discard")').first
            if discard_btn.count() > 0 and discard_btn.is_visible():
                discard_btn.click(force=True)
                page.wait_for_timeout(1000)
                confirm_discard = page.locator('div[role="dialog"] button:has-text("Discard")').first
                if confirm_discard.count() > 0 and confirm_discard.is_visible():
                    confirm_discard.click(force=True)
        except Exception:
            pass

        try:
            browser.close()
        except Exception:
            pass

        raise TikTokContentRestrictedError(f"TikTok content check flagged video: {reason}")

    def upload_via_api(self, video_path: Path, caption: Optional[str] = None) -> bool:
        """
        Uploads via official Content Posting API v2.
        """
        post_caption = caption or config.DEFAULT_CAPTION
        total_size = video_path.stat().st_size
        total_chunks = math.ceil(total_size / self.chunk_size)

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json; charset=UTF-8"
        }

        payload = {
            "post_info": {
                "title": post_caption,
                "privacy_level": "PUBLIC_TO_EVERYONE",
                "disable_duet": False,
                "disable_comment": False,
                "disable_stitch": False,
                "video_cover_timestamp_ms": 1000
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": total_size,
                "chunk_size": self.chunk_size,
                "total_chunk_count": total_chunks
            }
        }

        logger.info(f"Init TikTok API v2: Size={total_size} bytes, Chunks={total_chunks}")
        res = requests.post(INIT_UPLOAD_URL, headers=headers, json=payload, timeout=30)
        if res.status_code != 200:
            raise TikTokUploadError(f"Init failed: {res.status_code} {res.text}")

        data = res.json()
        upload_url = data.get("data", {}).get("upload_url")
        publish_id = data.get("data", {}).get("publish_id")

        if not upload_url or not publish_id:
            raise TikTokUploadError(f"Missing upload_url or publish_id: {data}")

        # Chunked upload
        with open(video_path, "rb") as f:
            chunk_idx = 0
            while True:
                start_byte = f.tell()
                chunk_data = f.read(self.chunk_size)
                if not chunk_data:
                    break
                end_byte = start_byte + len(chunk_data) - 1
                chunk_headers = {
                    "Content-Type": "video/mp4",
                    "Content-Range": f"bytes {start_byte}-{end_byte}/{total_size}",
                    "Content-Length": str(len(chunk_data))
                }
                c_res = requests.put(upload_url, headers=chunk_headers, data=chunk_data, timeout=60)
                if c_res.status_code not in (200, 201):
                    raise TikTokUploadError(f"Chunk {chunk_idx} failed: {c_res.status_code} {c_res.text}")
                chunk_idx += 1

        # Poll status
        start_time = time.time()
        while time.time() - start_time < 360:
            s_res = requests.post(STATUS_CHECK_URL, headers=headers, json={"publish_id": publish_id}, timeout=30)
            if s_res.status_code == 200:
                status = s_res.json().get("data", {}).get("status")
                if status == "SUCCESS":
                    logger.info("API v2 Publish verified successfully!")
                    return True
                elif status == "FAILED":
                    reason = s_res.json().get("data", {}).get("fail_reason", "Unknown")
                    raise TikTokUploadError(f"Publish failed: {reason}")
            time.sleep(10)

        raise TimeoutError("Publish status polling timed out.")

    def upload_video(self, video_path: Path, caption: Optional[str] = None) -> bool:
        """
        Unified upload router: Automatically selects Session ID or API v2.
        """
        if self.session_id and len(self.session_id) > 10 and self.session_id != "your_tiktok_session_id_here":
            logger.info("Using authenticated TikTok Studio Session for publishing...")
            return self.upload_via_playwright(video_path, caption)
        elif self.access_token and self.access_token != "your_tiktok_access_token_here":
            logger.info("Using TikTok Content Posting API v2 for publishing...")
            return self.upload_via_api(video_path, caption)
        else:
            raise TikTokUploadError(
                "Neither TIKTOK_SESSION_ID nor TIKTOK_ACCESS_TOKEN is configured in .env."
            )
