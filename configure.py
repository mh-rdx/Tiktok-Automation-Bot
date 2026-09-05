"""
Interactive Setup Assistant for TikTok Bot.
Helps the user configure Google Drive and TikTok API credentials interactively.
"""

import os
import json
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
SA_PATH = BASE_DIR / "service_account.json"

def update_env(updates: dict):
    env_lines = []
    if ENV_PATH.exists():
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            env_lines = f.readlines()

    existing_keys = set()
    new_lines = []
    for line in env_lines:
        match = re.match(r"^([A-Z_]+)=(.*)$", line.strip())
        if match:
            key = match.group(1)
            existing_keys.add(key)
            if key in updates:
                new_lines.append(f"{key}={updates[key]}\n")
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    for key, val in updates.items():
        if key not in existing_keys:
            new_lines.append(f"{key}={val}\n")

    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.writelines(new_lines)
    print(f"Updated .env successfully.")

def main():
    print("=" * 60)
    print("  TikTok Automation Bot - Interactive Credential Setup")
    print("=" * 60)
    print()

    # 1. Google Drive Folder ID
    print("Step 1: Google Drive Folder")
    print("Open your Drive folder in browser: https://drive.google.com/drive/folders/<FOLDER_ID>")
    raw_folder = input("Paste your Folder URL or Folder ID: ").strip()
    folder_id = raw_folder
    if "/folders/" in raw_folder:
        folder_id = raw_folder.split("/folders/")[-1].split("?")[0].strip()

    # 2. Service Account JSON
    print("\nStep 2: Google Cloud Service Account")
    print("If you have downloaded your Service Account JSON file, enter its path:")
    sa_input = input("File path (or press Enter to paste JSON text): ").strip()
    if sa_input and Path(sa_input).exists():
        with open(sa_input, "r", encoding="utf-8") as src, open(SA_PATH, "w", encoding="utf-8") as dst:
            dst.write(src.read())
        print(f"Copied service account file to: {SA_PATH}")
    elif not sa_input:
        print("Tip: You can also drop 'service_account.json' directly into this folder.")

    # 3. TikTok Credentials
    print("\nStep 3: TikTok API Credentials")
    tiktok_token = input("TikTok Access Token (press Enter to skip): ").strip()
    tiktok_openid = input("TikTok OpenID (press Enter to skip): ").strip()

    updates = {}
    if folder_id:
        updates["GOOGLE_DRIVE_FOLDER_ID"] = folder_id
    if tiktok_token:
        updates["TIKTOK_ACCESS_TOKEN"] = tiktok_token
    if tiktok_openid:
        updates["TIKTOK_OPEN_ID"] = tiktok_openid

    if updates:
        update_env(updates)

    print("\nSetup updated. Run 'python check_setup.py' to review status.")

if __name__ == "__main__":
    main()
