# ?? TikTok Automation Bot (24/7 Cloud Daemon)

Fully autonomous background pipeline that monitors a Google Drive folder for reels/shorts, applies a dynamic transparent channel watermark (scaled to 15% width), uploads them directly to TikTok Studio with session-based authentication and anti-bot evasion, archives processed videos, and enforces humanized anti-ban rate limiting (10 posts/day, 2-hour base interval + randomized jitter).

---

## ? Features
- **Google Drive Ingestion**: Supports direct MP4 video files and Google Drive Shortcuts (pplication/vnd.google-apps.shortcut) via Google Drive API v3.
- **Dynamic Watermarking**: Auto-scales the transparent channel logo (logo.png) to exactly 15% video width, rounded to even pixel dimensions for H.264 compliance, placed at bottom-right with customizable padding.
- **Headless TikTok Studio Upload**: Uses Playwright with stealth user-agent and session cookies (sessionid, sessionid_ss, sid_tt, sid_guard) to bypass TikTok Studio login and publish directly.
- **Intelligent Modal & Review Handling**: Automatically dismisses tutorial overlays, handles "Continue to post?" checks, and verifies redirect to /tiktokstudio/content.
- **Archive Queue System**: Successfully published reels are automatically moved into an Uploaded_Reels subfolder in Google Drive to prevent duplicates.
- **Anti-Ban Scheduling**: Strict 10 posts/day daily cap, 2-hour posting intervals, and randomized 1-10 minute jitter to mimic human creator activity.
- **24/7 Cloud Ready**: Fully containerized with Docker for 1-click 24/7 deployment on **Railway.app**.

---

## ?? Deploying to Railway.app (24/7 Running)

### Step 1: Push Code to GitHub
Ensure you have committed and pushed the repository:
`ash
git add .
git commit -m "Configure Railway deployment"
git push origin main
`

### Step 2: Create Railway Project
1. Log in to [Railway.app](https://railway.app/).
2. Click **New Project** -> **Deploy from GitHub repo**.
3. Select your Tiktok-Automation-Bot repository.
4. Railway will automatically detect the Dockerfile and start the build.

### Step 3: Set Environment Variables in Railway Dashboard
In Railway, go to your service -> **Variables** tab, and add:

| Variable Name | Description | Example / Value |
|---|---|---|
| GOOGLE_SERVICE_ACCOUNT_JSON | Entire JSON content of service_account.json | {"type": "service_account", ...} |
| GOOGLE_DRIVE_FOLDER_ID | Target folder ID in Google Drive | 1lxxXAiGpfbgcTuA0_vF51Vc6HOMR4aKS |
| TIKTOK_SESSION_ID | Your TikTok Studio sessionid cookie | 1c77fed174866cbc920ab44f292769c3 |
| DEFAULT_CAPTION | Viral caption & hashtags | Hansi nahi rukegi! ?? Follow for daily fun! #TimePass #FYP |
| DAILY_LIMIT | Max reels per day | 10 |
| POST_INTERVAL_SECONDS | Interval between posts (seconds) | 7200 |
| JITTER_MIN_SECONDS | Minimum random delay | 60 |
| JITTER_MAX_SECONDS | Maximum random delay | 600 |
| EMPTY_QUEUE_SLEEP_SECONDS| Delay when no new reels are found | 900 |

### Step 4: Verify Deployment
- Open the **Deploy Logs** tab on Railway.
- You will see:
  `	ext
  [INFO] [drive_service]: Google Drive v3 client initialized and authenticated successfully.
  [INFO] [Orchestrator]: TikTok Automation Background Daemon Online
  [INFO] [Orchestrator]: Daily Cap: 10 reels/day
  `
- Any reel dropped into your Google Drive folder will automatically be watermarked and published to TikTok 24/7!

---

## ?? Local Quickstart

### Prerequisites
- Python 3.10+
- FFmpeg installed & added to system PATH

### Setup
`ash
python -m venv venv
.\venv\Scripts\activate      # Windows
# source venv/bin/activate   # Linux/Mac

pip install -r requirements.txt
playwright install chromium

# Verify configuration
python check_setup.py

# Run daemon
python bot_orchestrator.py
`

---

## ?? Security
- **Never commit .env or service_account.json to GitHub!** They are included in .gitignore.
- On cloud services (Railway), pass credentials via environment variables.
