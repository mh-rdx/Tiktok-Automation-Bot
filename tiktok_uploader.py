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
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                locale="en-US",
                timezone_id="America/New_York"
            )

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

            # Inject session cookies
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
                        # Only add if not already in cookies list
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


                for btn_text in ["Turn on", "Got it", "Cancel"]:
                    try:
                        modal_btn = page.locator(f'button:has-text("{btn_text}")').first
                        if modal_btn.count() > 0 and modal_btn.is_visible():
                            logger.info(f"Dismissing modal button: '{btn_text}'")
                            modal_btn.click()
                            page.wait_for_timeout(1000)
                    except Exception:
                        pass

                try:
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(300)
                except Exception:
                    pass

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
                    if post_btn.is_enabled():
                        is_ready = True
                        logger.info("Post button is enabled and ready to publish!")
                        break
                    if attempt % 5 == 0:
                        logger.info(f"Video still processing on TikTok servers... ({attempt * 3}s elapsed)")
                    page.wait_for_timeout(3000)

                if not is_ready:
                    raise TikTokUploadError("Video processing timed out on TikTok Studio after 6 minutes.")

                # Scroll into view and click
                post_btn.scroll_into_view_if_needed()
                page.wait_for_timeout(500)
                logger.info("Clicking Post button...")
                post_btn.click(force=True)

                # Wait for publish confirmation or secondary modals
                logger.info("Waiting for publish confirmation & handling modals...")
                published = False
                for attempt in range(60):  # 60 * 2s = 120 seconds
                    page.wait_for_timeout(2000)

                    # 1. If "Continue to post?" modal appears, click "Post now"!
                    post_now_btn = page.locator('button:has-text("Post now"), button:text-is("Post now")').first
                    if post_now_btn.count() > 0 and post_now_btn.is_visible():
                        logger.info("Detected 'Continue to post?' modal! Clicking 'Post now' button...")
                        post_now_btn.click(force=True)
                        page.wait_for_timeout(2000)

                    # 2. If unsaved changes modal appears, click "Cancel" to remain on page
                    exit_btn = page.locator('button:has-text("Exit")').first
                    if exit_btn.count() > 0 and exit_btn.is_visible():
                        logger.warning("Unsaved changes modal detected! Clicking Cancel...")
                        cancel_btn = page.locator('button:text-is("Cancel")').first
                        if cancel_btn.count() > 0:
                            cancel_btn.click(force=True)

                    url = page.url
                    content = page.content().lower()
                    if (
                        "/content" in url
                        or "your video has been uploaded" in content
                        or "manage your posts" in content
                        or "post another video" in content
                        or "view post" in content
                    ):
                        logger.info(f"TikTok post published successfully! Confirmation detected (URL: {url})")
                        published = True
                        break

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
