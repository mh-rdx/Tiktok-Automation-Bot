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
                self._dismiss_advisory_and_check_modals(page)

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
                    # Regularly dismiss any check/advisory modals that pop up during processing
                    self._dismiss_advisory_and_check_modals(page)

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

                # Dismiss any lingering advisory modals before clicking Post
                self._dismiss_advisory_and_check_modals(page)

                # Scroll into view and click
                post_btn.scroll_into_view_if_needed()
                page.wait_for_timeout(500)
                logger.info("Clicking Post button...")
                post_btn.click(force=True)

                # Wait for publish confirmation & actively handle all secondary modals
                logger.info("Waiting for publish confirmation & actively handling any confirmation/advisory modals...")
                published = False
                for attempt in range(60):  # 60 * 2s = 120 seconds
                    page.wait_for_timeout(2000)

                    # 1. Handle confirmation modals (e.g. "Post now", "Post anyway", "Continue to post")
                    self._handle_post_confirmation_modals(page)

                    # 2. Dismiss any advisory modals (e.g. "Content may be restricted", "Copyright check")
                    self._dismiss_advisory_and_check_modals(page)

                    # 3. Check for successful publish confirmation
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

                    # 4. If main Post button is STILL visible and enabled (modal previously blocked it), re-click Post!
                    if attempt % 3 == 0 and attempt > 0:
                        try:
                            re_post = page.locator(
                                'button.Button__root--type-primary:has-text("Post"), '
                                'button:not([data-tt*="Sidebar"]):text-is("Post"), '
                                'button:not([data-tt*="Sidebar"]):has-text("Post")'
                            ).first
                            if re_post.count() > 0 and re_post.is_visible() and re_post.is_enabled():
                                logger.info("Main 'Post' button is still visible and ready. Re-clicking Post...")
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

            except Exception as e:
                err_pic = config.TEMP_DIR / "tiktok_error.png"
                try:
                    page.screenshot(path=str(err_pic))
                    logger.warning(f"Saved error screenshot to {err_pic}")
                except Exception:
                    pass
                browser.close()
                raise TikTokUploadError(f"Playwright TikTok upload failed: {e}")

    def _dismiss_advisory_and_check_modals(self, page) -> bool:
        """
        Detects and safely dismisses advisory or check modals on TikTok Studio:
        - 'Content may be restricted' (Content check lite / Unoriginal content warning)
        - 'Music copyright check'
        - 'Turn on high quality' / Permissions
        - Benign onboarding prompts
        Returns True if a modal was handled.
        """
        handled = False
        try:
            # 1. Check if 'Content may be restricted' or similar advisory text is present
            page_text = page.content().lower()
            advisory_keywords = [
                "content may be restricted",
                "unoriginal, low-quality",
                "violation reason",
                "content check lite",
                "music copyright check",
                "copyright issue",
            ]
            if any(kw in page_text for kw in advisory_keywords):
                # Acknowledge / continue buttons if present
                for ack_text in ["Post anyway", "Continue to post", "Publish anyway", "Got it", "Understood", "I understand", "Dismiss", "Acknowledge"]:
                    try:
                        ack_btn = page.locator(f'button:has-text("{ack_text}")').first
                        if ack_btn.count() > 0 and ack_btn.is_visible():
                            logger.info(f"Clicking modal acknowledgment button: '{ack_text}'")
                            ack_btn.click(force=True)
                            page.wait_for_timeout(1000)
                            handled = True
                            break
                    except Exception:
                        pass

                # Look for modal close 'X' button inside modal dialog
                close_selectors = [
                    'div[role="dialog"] button[aria-label*="close" i]',
                    'div[role="dialog"] button[aria-label*="Close" i]',
                    'div[role="dialog"] button:has(svg)',
                    '.TUXModal button[aria-label*="close" i]',
                    '.tux-modal button:has(svg)',
                    'div[class*="modal" i] button[aria-label*="close" i]',
                    'div[class*="modal" i] button:has(svg)',
                    'button[aria-label="Close"]',
                    'button[aria-label="close"]',
                ]
                for sel in close_selectors:
                    try:
                        c_btn = page.locator(sel).first
                        if c_btn.count() > 0 and c_btn.is_visible():
                            btn_text = c_btn.inner_text().strip().lower()
                            # Never click 'replace video' or 'cancel'
                            if "replace" not in btn_text and "cancel" not in btn_text:
                                logger.info(f"Dismissing advisory modal via close button ({sel})")
                                c_btn.click(force=True)
                                page.wait_for_timeout(1000)
                                handled = True
                                break
                    except Exception:
                        pass

                # Press Escape as fallback to dismiss open modal
                try:
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(500)
                except Exception:
                    pass

            # 2. General benign modals ("Turn on", "Got it", "Not now", "Dismiss", "Close")
            for btn_text in ["Turn on", "Got it", "Not now", "Dismiss", "Close"]:
                try:
                    m_btn = page.locator(f'button:text-is("{btn_text}"), button:has-text("{btn_text}")').first
                    if m_btn.count() > 0 and m_btn.is_visible():
                        logger.info(f"Dismissing benign modal button: '{btn_text}'")
                        m_btn.click(force=True)
                        page.wait_for_timeout(500)
                        handled = True
                except Exception:
                    pass

            # 3. Safety check: if 'Sure you want to cancel your upload?' dialog appears, click 'No'
            try:
                no_btn = page.locator('button:text-is("No"), button:has-text("No")').first
                if no_btn.count() > 0 and no_btn.is_visible():
                    logger.info("Dismissed unexpected cancel upload dialog by clicking 'No'.")
                    no_btn.click(force=True)
                    page.wait_for_timeout(500)
                    handled = True
            except Exception:
                pass

        except Exception as e:
            logger.debug(f"Notice in _dismiss_advisory_and_check_modals: {e}")

        return handled

    def _handle_post_confirmation_modals(self, page) -> bool:
        """
        Detects if clicking Post prompted a secondary confirmation dialog:
        - 'Post now'
        - 'Post anyway'
        - 'Continue to post'
        - 'Publish anyway'
        - 'Confirm'
        Clicks the confirmation to finalize publishing.
        """
        handled = False
        try:
            for btn_text in [
                "Post now",
                "Post anyway",
                "Continue to post",
                "Publish anyway",
                "Confirm post",
                "Confirm",
            ]:
                try:
                    btn = page.locator(f'button:text-is("{btn_text}"), button:has-text("{btn_text}")').first
                    if btn.count() > 0 and btn.is_visible():
                        logger.info(f"Detected post confirmation dialog! Clicking: '{btn_text}'")
                        btn.click(force=True)
                        page.wait_for_timeout(2000)
                        handled = True
                        break
                except Exception:
                    pass

            # If unsaved changes modal appears, click "Cancel" to remain on page
            exit_btn = page.locator('button:has-text("Exit")').first
            if exit_btn.count() > 0 and exit_btn.is_visible():
                logger.warning("Unsaved changes modal detected! Clicking Cancel...")
                cancel_btn = page.locator('button:text-is("Cancel")').first
                if cancel_btn.count() > 0:
                    cancel_btn.click(force=True)
                    handled = True

        except Exception as e:
            logger.debug(f"Notice in _handle_post_confirmation_modals: {e}")

        return handled

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
