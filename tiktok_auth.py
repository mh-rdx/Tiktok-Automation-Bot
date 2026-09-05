"""
Interactive 1-Click TikTok OAuth Helper.
Starts a local web server, opens the browser for 1-click TikTok authorization,
exchanges the auth code for access_token and open_id, and writes them into .env.
"""

import os
import re
import sys
import webbrowser
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH)

CLIENT_KEY = os.getenv("TIKTOK_CLIENT_KEY", "").strip()
CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET", "").strip()
REDIRECT_URI = "http://localhost:8080/callback"
SCOPES = "user.info.basic,video.upload,video.publish"

auth_code_received = None

class OAuthCallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code_received
        parsed_url = urllib.parse.urlparse(self.path)
        query_params = urllib.parse.parse_qs(parsed_url.query)

        if "code" in query_params:
            auth_code_received = query_params["code"][0]
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            html = """
            <html>
            <body style="font-family: sans-serif; text-align: center; padding: 50px;">
                <h1 style="color: #00c853;">Authorization Successful!</h1>
                <p>You can close this tab now and return to your terminal.</p>
            </body>
            </html>
            """
            self.wfile.write(html.encode("utf-8"))
        else:
            err = query_params.get("error_description", ["Unknown error"])[0]
            self.send_response(400)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"<h1>Authorization Failed: {err}</h1>".encode("utf-8"))

    def log_message(self, format, *args):
        # Suppress noisy HTTP server logs
        pass

def update_env(key_values: dict):
    env_lines = []
    if ENV_PATH.exists():
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            env_lines = f.readlines()

    existing_keys = set()
    new_lines = []
    for line in env_lines:
        match = re.match(r"^([A-Z_]+)=(.*)$", line.strip())
        if match:
            k = match.group(1)
            existing_keys.add(k)
            if k in key_values:
                new_lines.append(f"{k}={key_values[k]}\n")
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    for k, v in key_values.items():
        if k not in existing_keys:
            new_lines.append(f"{k}={v}\n")

    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

def exchange_code_for_token(code: str):
    token_url = "https://open.tiktokapis.com/v2/oauth/token/"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Cache-Control": "no-cache"
    }
    payload = {
        "client_key": CLIENT_KEY,
        "client_secret": CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI
    }

    print("\nExchanging authorization code with TikTok API...")
    res = requests.post(token_url, headers=headers, data=payload, timeout=30)
    data = res.json()

    if res.status_code != 200 or data.get("error"):
        print(f"[ERROR] Token exchange failed: {data}")
        return False

    token_data = data.get("data", {})
    access_token = token_data.get("access_token")
    open_id = token_data.get("open_id")

    if not access_token:
        # Check top level for legacy responses
        access_token = data.get("access_token")
        open_id = data.get("open_id")

    if access_token:
        update_env({
            "TIKTOK_ACCESS_TOKEN": access_token,
            "TIKTOK_OPEN_ID": open_id or ""
        })
        print("=" * 60)
        print("SUCCESS! TikTok Access Token & OpenID retrieved and saved to .env!")
        print(f"OpenID: {open_id}")
        print("=" * 60)
        return True
    else:
        print(f"[ERROR] Could not extract access_token from response: {data}")
        return False

def main():
    if not CLIENT_KEY or not CLIENT_SECRET:
        print("[ERROR] TIKTOK_CLIENT_KEY or TIKTOK_CLIENT_SECRET missing in .env.")
        sys.exit(1)

    auth_url = (
        f"https://www.tiktok.com/v2/auth/authorize/"
        f"?client_key={CLIENT_KEY}"
        f"&scope={SCOPES}"
        f"&response_type=code"
        f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
        f"&state=tiktok_bot_state_123"
    )

    server = HTTPServer(("localhost", 8080), OAuthCallbackHandler)
    print("=" * 65)
    print("  TikTok 1-Click Authorization Service")
    print("=" * 65)
    print(f"Opening browser for authorization...")
    print(f"Auth URL: {auth_url}\n")
    print("Listening on http://localhost:8080/callback for authorization code...")

    webbrowser.open(auth_url)

    # Handle single request
    while auth_code_received is None:
        server.handle_request()

    server.server_close()

    if auth_code_received:
        success = exchange_code_for_token(auth_code_received)
        if success:
            print("\nRun 'python check_setup.py' to verify readiness!")

if __name__ == "__main__":
    main()
