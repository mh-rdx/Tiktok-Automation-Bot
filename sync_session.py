"""
TIME PASS - TikTok Standalone Session Manager & Login Helper
Solves:
1. Google OAuth / Gmail sign-in block ("This browser or app may not be secure"):
   Launches genuine Google Chrome / Microsoft Edge via CDP with navigator.webdriver=False.
2. QR / Email rate limits:
   Allows 1-click import from 'cookies.json' or direct paste from Cookie-Editor extension.
"""

import os
import sys
import time
import json
import shutil
import subprocess
import threading
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SESSION_FILE = BASE_DIR / "tiktok_session.json"
COOKIES_JSON_FILE = BASE_DIR / "cookies.json"


def normalize_samesite(val):
    v = str(val or "").strip().lower()
    if v == "strict":
        return "Strict"
    if v == "lax":
        return "Lax"
    return "None"


def find_system_browser():
    """Finds installed Google Chrome or Microsoft Edge on Windows."""
    candidates = [
        # Chrome
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
        # Edge
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


def convert_and_save_cookies(raw_cookies) -> bool:
    """Takes a list or dict of cookies and saves in Playwright storage_state format."""
    if isinstance(raw_cookies, dict):
        cookie_list = raw_cookies.get("cookies", [])
    elif isinstance(raw_cookies, list):
        cookie_list = raw_cookies
    else:
        print("❌ Invalid cookie format. Expected JSON list or object.")
        return False

    pw_cookies = []
    has_session = False

    for c in cookie_list:
        if not isinstance(c, dict):
            continue
        name = str(c.get("name", "")).strip()
        val = str(c.get("value", "")).strip()
        if not name or not val:
            continue

        if name in ["sessionid", "sessionid_ss", "sid_tt"]:
            has_session = True

        raw_ss = c.get("sameSite", "")
        exp = c.get("expirationDate") or c.get("expires") or (int(time.time()) + 86400 * 30)

        pw_cookies.append({
            "name": name,
            "value": val,
            "domain": c.get("domain", ".tiktok.com"),
            "path": c.get("path", "/"),
            "expires": float(exp),
            "httpOnly": bool(c.get("httpOnly", False)),
            "secure": bool(c.get("secure", False)),
            "sameSite": normalize_samesite(raw_ss)
        })

    if not pw_cookies:
        print("❌ No valid cookies found in provided data.")
        return False

    storage_data = {
        "cookies": pw_cookies,
        "origins": []
    }

    with open(SESSION_FILE, "w", encoding="utf-8") as f:
        json.dump(storage_data, f, indent=2)

    print(f"\n✅ Successfully saved {len(pw_cookies)} cookies to {SESSION_FILE.name}!")
    if has_session:
        print("🎉 Valid TikTok sessionid detected!")
    else:
        print("⚠️ Note: sessionid was not in the cookies, but full state was saved.")
    return True


def import_from_file_or_paste():
    """Import cookies either from cookies.json file or direct paste."""
    if COOKIES_JSON_FILE.exists():
        print(f"📁 Found existing '{COOKIES_JSON_FILE.name}' in folder!")
        try:
            with open(COOKIES_JSON_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if convert_and_save_cookies(data):
                return True
        except Exception as e:
            print(f"Error reading {COOKIES_JSON_FILE.name}: {e}")

    print("\n" + "=" * 65)
    print("📋 PASTE COOKIE-EDITOR JSON")
    print("=" * 65)
    print("Steps:")
    print("1. In normal Chrome/Edge, open TikTok and ensure you are logged in.")
    print("2. Click 'Cookie-Editor' extension -> Export -> Export JSON.")
    print("3. Paste the copied JSON below and press [ENTER], then press Ctrl+Z (or Enter twice):")
    print("-" * 65)

    lines = []
    try:
        while True:
            line = input()
            if not line.strip() and lines:
                break
            lines.append(line)
    except EOFError:
        pass

    raw_text = "\n".join(lines).strip()
    if not raw_text:
        print("❌ No input received.")
        return False

    try:
        data = json.loads(raw_text)
        return convert_and_save_cookies(data)
    except Exception as e:
        print(f"❌ Failed to parse JSON: {e}")
        return False


def launch_real_browser_login():
    """
    Launches real Google Chrome or Edge with remote debugging port.
    This BYPASSES Google's 'This browser or app may not be secure' block,
    allowing full Google OAuth / Gmail sign-in!
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("📦 Installing playwright...")
        os.system(f"{sys.executable} -m pip install playwright")
        from playwright.sync_api import sync_playwright

    browser_exe = find_system_browser()
    temp_profile = Path.home() / "AppData" / "Local" / "Temp" / "tiktok_login_profile"

    # Clean previous temp profile if needed
    if temp_profile.exists():
        try:
            shutil.rmtree(temp_profile, ignore_errors=True)
        except Exception:
            pass

    proc = None
    cdp_port = 9222

    if browser_exe:
        print(f"\n🚀 Launching genuine system browser: {Path(browser_exe).name}")
        print("💡 Google OAuth / Gmail sign-in is FULLY SUPPORTED (No security blocks!)")
        cmd = [
            browser_exe,
            f"--remote-debugging-port={cdp_port}",
            f"--user-data-dir={temp_profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "https://www.tiktok.com/tiktokstudio"
        ]
        try:
            proc = subprocess.Popen(cmd)
            time.sleep(2)
        except Exception as e:
            print(f"⚠️ Could not launch system browser directly ({e}), falling back to Playwright...")
            proc = None

    with sync_playwright() as p:
        if proc:
            try:
                browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{cdp_port}")
                context = browser.contexts[0] if browser.contexts else browser.new_context()
                page = context.pages[0] if context.pages else context.new_page()
            except Exception as ce:
                print(f"⚠️ CDP connection notice ({ce}). Falling back to direct launch...")
                proc.terminate()
                proc = None

        if not proc:
            browser = p.chromium.launch(
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--window-size=1280,900"
                ]
            )
            context = browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                locale="en-US"
            )
            page = context.new_page()
            page.goto("https://www.tiktok.com/tiktokstudio", wait_until="domcontentloaded")

        print("\n" + "=" * 65)
        print("🌐 TikTok Studio login page is now open!")
        print("👉 You can now click 'Continue with Google' and enter your Gmail!")
        print("👉 (Or use Phone / Email / QR Code)")
        print()
        print("👉 Once logged in to TikTok Studio, press [ENTER] here in this terminal.")
        print("=" * 65)

        user_pressed_enter = threading.Event()

        def wait_for_enter():
            try:
                input("👉 Press [ENTER] when you are logged in: ")
                user_pressed_enter.set()
            except Exception:
                pass

        input_thread = threading.Thread(target=wait_for_enter, daemon=True)
        input_thread.start()

        start_time = time.time()
        while not user_pressed_enter.is_set():
            time.sleep(2)
            try:
                cookies = context.cookies()
                c_names = [c["name"] for c in cookies]
                if "sessionid" in c_names and ("sid_tt" in c_names or "uid_tt" in c_names):
                    cur_url = page.url.lower()
                    if "login" not in cur_url and "tiktokstudio" in cur_url:
                        print("\n🎉 Active TikTok Studio session detected!")
                        break
            except Exception:
                pass

            if time.time() - start_time > 400:
                print("\n⏰ Time elapsed.")
                break

        print("\n📦 Capturing session cookies...")
        time.sleep(2)

        try:
            cookies = context.cookies()
            convert_and_save_cookies(cookies)
        except Exception as e:
            print(f"⚠️ Error saving cookies from browser context: {e}")

        try:
            browser.close()
        except Exception:
            pass

    if proc:
        try:
            proc.terminate()
        except Exception:
            pass

    return SESSION_FILE.exists()


def main():
    print("=" * 65)
    print("      TIME PASS | TikTok 1-Click Login & Session Saver")
    print("=" * 65)

    # Check if user already placed a cookies.json file in the directory
    if COOKIES_JSON_FILE.exists():
        print(f"📁 Detected '{COOKIES_JSON_FILE.name}' in folder!")
        print("Attempting automatic import...")
        if import_from_file_or_paste():
            print("\n🎉 All set! You can now run 'run_bot.bat' to start the bot.")
            return

    print("\nHow would you like to log in?")
    print(" [1] Launch Real Chrome/Edge (Google / Gmail Login Supported!)  [DEFAULT]")
    print(" [2] Paste Cookies JSON from Cookie-Editor Extension")
    print()

    choice = input("Select [1 or 2, press ENTER for 1]: ").strip()

    if choice == "2":
        success = import_from_file_or_paste()
    else:
        success = launch_real_browser_login()

    if success:
        print("\n" + "=" * 65)
        print("🎉 ALL DONE! TikTok session is saved to tiktok_session.json.")
        print("🚀 You can now double-click 'run_bot.bat' to start the 24/7 bot!")
        print("=" * 65)
    else:
        print("\n❌ Login was not completed. Please try again.")


if __name__ == "__main__":
    main()
