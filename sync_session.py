"""
1-Click TikTok Session Exporter & Browser Login Tool.
Launches a visible Chromium window on your desktop.
Logs in via QR Code, Google, Email, or Phone.
Saves the authenticated session directly into tiktok_session.json.
"""

import os
import sys
import time
import json
import threading
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SESSION_FILE = BASE_DIR / "tiktok_session.json"


def normalize_samesite(val):
    v = str(val or "").strip().lower()
    if v == "strict":
        return "Strict"
    if v == "lax":
        return "Lax"
    return "None"


def main():
    print("=" * 65)
    print("      TIME PASS | TikTok 1-Click Login & Session Saver")
    print("=" * 65)
    print()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("❌ Playwright is required. Installing playwright...")
        os.system(f"{sys.executable} -m pip install playwright")
        os.system(f"{sys.executable} -m playwright install chromium")
        from playwright.sync_api import sync_playwright

    print("🚀 Launching visible browser window on your desktop...")
    print("👉 When the browser opens, log in to your TikTok account:")
    print("   - Scan QR code using your mobile TikTok app (FASTEST & EASIEST!)")
    print("   - Or use 'Continue with Google'")
    print("   - Or use 'Use phone / email / username'")
    print()
    print("👉 Once you are logged in to TikTok Studio, press [ENTER] here in this terminal.")
    print("=" * 65)

    with sync_playwright() as p:
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
        # Anti-bot detection stealth
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            window.chrome = { runtime: {} };
        """)

        page = context.new_page()
        login_url = "https://www.tiktok.com/tiktokstudio"
        print(f"\n🌐 Opening {login_url}...")
        try:
            page.goto(login_url, wait_until="domcontentloaded")
        except Exception as ge:
            print(f"Notice during navigation: {ge}")

        print("\n⏳ Browser is now open! Please log in...")
        print("💡 When you see your TikTok Studio or Profile, press [ENTER] below to save session:\n")

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
            # Check if auto-detected
            try:
                cookies = context.cookies()
                cookie_names = [c["name"] for c in cookies]
                if "sessionid" in cookie_names and ("sid_tt" in cookie_names or "uid_tt" in cookie_names):
                    cur_url = page.url.lower()
                    if "login" not in cur_url and "tiktokstudio" in cur_url:
                        print("\n🎉 Auto-detected active sessionid and TikTok login!")
                        break
            except Exception:
                pass

            # Timeout after 5 minutes if no response
            if time.time() - start_time > 300:
                print("\n⏰ 5 minutes elapsed.")
                break

        print("\n📦 Capturing full session cookies and storage state...")
        time.sleep(2)

        # Export storage state
        context.storage_state(path=str(SESSION_FILE))

        # Normalize sameSite in saved session file
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                s_data = json.load(f)
            pw_cookies = s_data.get("cookies", [])
            for c in pw_cookies:
                c["sameSite"] = normalize_samesite(c.get("sameSite"))
            with open(SESSION_FILE, "w", encoding="utf-8") as f:
                json.dump(s_data, f, indent=2)
            print(f"✅ Successfully saved {len(pw_cookies)} cookies to {SESSION_FILE.name}!")
        except Exception as e:
            print(f"⚠️ Note on saving: {e}")

        browser.close()

    print("\n" + "=" * 65)
    print("🎉 ALL DONE! Your TikTok session is ready on this machine.")
    print("🚀 You can now double-click 'run_bot.bat' to start the 24/7 bot!")
    print("=" * 65)


if __name__ == "__main__":
    main()
