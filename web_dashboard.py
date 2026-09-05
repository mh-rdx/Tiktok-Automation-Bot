"""
Live Web Dashboard & REST Monitoring API.
Serves a modern glassmorphic dashboard on $PORT (default: 8080) for Railway.
"""

import os
import sys
import time
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, jsonify, render_template_string, send_file, request

import config

app = Flask(__name__)
# Suppress noisy flask request logs
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# In-memory shared status
bot_state = {
    "status": "Online & Monitoring",
    "sub_status": "Waiting for schedule or new video",
    "start_time": datetime.now(),
    "last_post_time": None,
    "last_post_name": None,
    "next_post_time": None,
    "posts_today": 0,
    "daily_limit": config.DAILY_LIMIT,
    "total_posts": 0,
    "drive_queue_count": 0,
    "recent_posts": [],
    "manual_trigger_requested": False
}

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>TIME PASS | TikTok Bot Dashboard</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #07090e;
      --card-bg: rgba(18, 24, 38, 0.7);
      --card-border: rgba(255, 255, 255, 0.08);
      --accent: #fe2c55;
      --accent-grad: linear-gradient(135deg, #fe2c55 0%, #25f4ee 100%);
      --text: #f3f4f6;
      --text-muted: #9ca3af;
      --success: #10b981;
      --warning: #f59e0b;
      --cyan: #25f4ee;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Outfit', sans-serif;
      background: radial-gradient(circle at top, #141c2e 0%, #07090e 100%);
      color: var(--text);
      min-height: 100vh;
      padding: 24px 16px;
    }
    .container {
      max-width: 1100px;
      margin: 0 auto;
    }
    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding-bottom: 24px;
      border-bottom: 1px solid var(--card-border);
      margin-bottom: 24px;
      flex-wrap: wrap;
      gap: 16px;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 16px;
    }
    .brand img {
      width: 54px;
      height: 54px;
      border-radius: 14px;
      background: #fff;
      padding: 2px;
      box-shadow: 0 0 20px rgba(254, 44, 85, 0.4);
    }
    .brand-title h1 {
      font-size: 26px;
      font-weight: 800;
      letter-spacing: -0.5px;
      background: var(--accent-grad);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }
    .brand-title p {
      font-size: 13px;
      color: var(--text-muted);
    }
    .live-badge {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      background: rgba(16, 185, 129, 0.12);
      border: 1px solid rgba(16, 185, 129, 0.3);
      color: #34d399;
      padding: 8px 16px;
      border-radius: 9999px;
      font-size: 13px;
      font-weight: 600;
      letter-spacing: 0.5px;
    }
    .pulse-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #10b981;
      box-shadow: 0 0 10px #10b981;
      animation: pulse 1.8s infinite;
    }
    @keyframes pulse {
      0% { transform: scale(0.95); opacity: 0.8; }
      50% { transform: scale(1.4); opacity: 1; box-shadow: 0 0 16px #10b981; }
      100% { transform: scale(0.95); opacity: 0.8; }
    }
    .banner-status {
      background: var(--card-bg);
      backdrop-filter: blur(12px);
      border: 1px solid var(--card-border);
      border-radius: 18px;
      padding: 18px 24px;
      margin-bottom: 24px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 16px;
    }
    .status-left h3 {
      font-size: 14px;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 1px;
      margin-bottom: 4px;
    }
    .status-left p {
      font-size: 20px;
      font-weight: 700;
      color: var(--cyan);
    }
    .btn-trigger {
      background: var(--accent);
      color: white;
      border: none;
      padding: 12px 22px;
      border-radius: 12px;
      font-weight: 700;
      font-size: 14px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 8px;
      transition: all 0.2s ease;
      box-shadow: 0 4px 14px rgba(254, 44, 85, 0.4);
    }
    .btn-trigger:hover {
      transform: translateY(-2px);
      box-shadow: 0 6px 20px rgba(254, 44, 85, 0.6);
    }
    .grid-stats {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 18px;
      margin-bottom: 24px;
    }
    .card {
      background: var(--card-bg);
      backdrop-filter: blur(12px);
      border: 1px solid var(--card-border);
      border-radius: 18px;
      padding: 20px;
      transition: transform 0.2s ease;
    }
    .card:hover {
      transform: translateY(-2px);
      border-color: rgba(255, 255, 255, 0.15);
    }
    .card-label {
      font-size: 13px;
      color: var(--text-muted);
      font-weight: 500;
      margin-bottom: 8px;
    }
    .card-value {
      font-size: 28px;
      font-weight: 800;
      letter-spacing: -0.5px;
      margin-bottom: 4px;
    }
    .card-sub {
      font-size: 12px;
      color: var(--text-muted);
    }
    .progress-bar-bg {
      background: rgba(255, 255, 255, 0.08);
      border-radius: 9999px;
      height: 8px;
      overflow: hidden;
      margin-top: 12px;
    }
    .progress-bar-fill {
      background: var(--accent-grad);
      height: 100%;
      border-radius: 9999px;
      transition: width 0.5s ease;
    }
    .logs-panel {
      background: #030508;
      border: 1px solid var(--card-border);
      border-radius: 18px;
      padding: 20px;
      font-family: 'JetBrains Mono', monospace;
    }
    .logs-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 12px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.06);
      padding-bottom: 10px;
    }
    .logs-header h3 {
      font-size: 14px;
      color: var(--text-muted);
      font-family: 'Outfit', sans-serif;
    }
    .logs-content {
      font-size: 12px;
      line-height: 1.6;
      max-height: 280px;
      overflow-y: auto;
      color: #cbd5e1;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .log-line {
      margin-bottom: 4px;
    }
    .log-info { color: #60a5fa; }
    .log-warn { color: #fbbf24; }
    .log-err { color: #f87171; }
    footer {
      text-align: center;
      margin-top: 36px;
      font-size: 13px;
      color: var(--text-muted);
    }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div class="brand">
        <img src="/logo.png" alt="TIME PASS Logo" onerror="this.style.display='none'">
        <div class="brand-title">
          <h1>TIME PASS Automation</h1>
          <p>Autonomous TikTok 24/7 Cloud Engine</p>
        </div>
      </div>
      <div class="live-badge">
        <span class="pulse-dot"></span>
        <span id="daemon-badge">DAEMON ONLINE</span>
      </div>
    </header>

    <div class="banner-status">
      <div class="status-left">
        <h3>Current Bot Activity</h3>
        <p id="current-status">Checking queue...</p>
        <span id="current-substatus" style="font-size: 13px; color: var(--text-muted);"></span>
      </div>
      <button class="btn-trigger" onclick="triggerManualPost()">
        <span>??</span> Post Next Reel Now
      </button>
    </div>

    <div class="grid-stats">
      <div class="card">
        <div class="card-label">Uploaded Today</div>
        <div class="card-value" id="posts-today">0 / 10</div>
        <div class="card-sub">Target Daily Cap: 10 Reels</div>
        <div class="progress-bar-bg">
          <div class="progress-bar-fill" id="daily-bar" style="width: 0%;"></div>
        </div>
      </div>

      <div class="card">
        <div class="card-label">Next Scheduled Post</div>
        <div class="card-value" id="next-post-countdown">--:--:--</div>
        <div class="card-sub" id="next-post-time">Interval: 2 Hours + Anti-Ban Jitter</div>
      </div>

      <div class="card">
        <div class="card-label">Queue in Google Drive</div>
        <div class="card-value" id="drive-queue">--</div>
        <div class="card-sub">Pending unprocessed reels</div>
      </div>

      <div class="card">
        <div class="card-label">Daemon Uptime</div>
        <div class="card-value" id="uptime">0m</div>
        <div class="card-sub" id="start-date">24/7 Continuous Execution</div>
      </div>
    </div>

    <div class="logs-panel">
      <div class="logs-header">
        <h3>Live Operational Logs</h3>
        <span style="font-size: 11px; color: var(--text-muted);">Auto-refreshes every 4s</span>
      </div>
      <div class="logs-content" id="logs-view">Connecting to daemon telemetry...</div>
    </div>

    <footer>
      <p>TIME PASS &bull; TikTok Cloud Bot Daemon &bull; Running on Railway.app</p>
    </footer>
  </div>

  <script>
    let countdownInterval = null;
    let nextPostTimestamp = null;

    async function fetchStats() {
      try {
        const res = await fetch('/api/status');
        if (!res.ok) return;
        const data = await res.json();

        document.getElementById('current-status').innerText = data.status;
        document.getElementById('current-substatus').innerText = data.sub_status || '';
        document.getElementById('posts-today').innerText = ${data.posts_today} / ;
        
        const pct = Math.min(100, (data.posts_today / data.daily_limit) * 100);
        document.getElementById('daily-bar').style.width = ${pct}%;

        document.getElementById('drive-queue').innerText = ${data.drive_queue_count} reels;
        document.getElementById('uptime').innerText = data.uptime_str;

        nextPostTimestamp = data.next_post_time;
        if (data.next_post_str) {
          document.getElementById('next-post-time').innerText = Scheduled: ;
        }

        // Render logs
        const logsDiv = document.getElementById('logs-view');
        if (data.recent_logs && data.recent_logs.length > 0) {
          logsDiv.innerHTML = data.recent_logs.map(l => {
            let cls = 'log-line';
            if (l.includes('[ERROR]')) cls += ' log-err';
            else if (l.includes('[WARNING]')) cls += ' log-warn';
            else if (l.includes('[INFO]')) cls += ' log-info';
            return <div class=""></div>;
          }).join('');
          logsDiv.scrollTop = logsDiv.scrollHeight;
        }

      } catch (err) {
        console.error('Stats fetch error:', err);
      }
    }

    function escapeHtml(str) {
      return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }

    function updateCountdown() {
      if (!nextPostTimestamp) {
        document.getElementById('next-post-countdown').innerText = 'Ready / Active';
        return;
      }
      const target = new Date(nextPostTimestamp).getTime();
      const now = new Date().getTime();
      const diff = target - now;
      if (diff <= 0) {
        document.getElementById('next-post-countdown').innerText = 'Due Now';
      } else {
        const hours = Math.floor(diff / (1000 * 60 * 60));
        const mins = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
        const secs = Math.floor((diff % (1000 * 60)) / 1000);
        document.getElementById('next-post-countdown').innerText = 
          ${String(hours).padStart(2,'0')}::;
      }
    }

    async function triggerManualPost() {
      if (!confirm("Are you sure you want to trigger an immediate post right now?")) return;
      try {
        const res = await fetch('/api/trigger', { method: 'POST' });
        const data = await res.json();
        alert(data.message || "Manual post triggered! Bot is processing queue.");
        fetchStats();
      } catch (e) {
        alert("Error triggering post: " + e);
      }
    }

    setInterval(fetchStats, 4000);
    setInterval(updateCountdown, 1000);
    fetchStats();
  </script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(DASHBOARD_HTML)

@app.route("/logo.png")
def logo():
    if config.WATERMARK_PATH.exists():
        return send_file(str(config.WATERMARK_PATH), mimetype="image/png")
    return "", 404

@app.route("/api/status")
def status():
    now = datetime.now()
    uptime_sec = int((now - bot_state["start_time"]).total_seconds())
    hrs, remainder = divmod(uptime_sec, 3600)
    mins, secs = divmod(remainder, 60)
    uptime_str = f"{hrs}h {mins}m {secs}s" if hrs > 0 else f"{mins}m {secs}s"

    # Read last 40 lines of bot.log if present
    recent_logs = []
    log_file = config.BASE_DIR / "bot.log"
    if log_file.exists():
        try:
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
                recent_logs = [line.strip() for line in lines[-40:] if line.strip()]
        except Exception:
            pass

    next_post_iso = bot_state["next_post_time"].isoformat() if bot_state["next_post_time"] else None
    next_post_str = bot_state["next_post_time"].strftime("%I:%M:%S %p") if bot_state["next_post_time"] else None

    return jsonify({
        "status": bot_state["status"],
        "sub_status": bot_state["sub_status"],
        "uptime_str": uptime_str,
        "posts_today": bot_state["posts_today"],
        "daily_limit": bot_state["daily_limit"],
        "total_posts": bot_state["total_posts"],
        "drive_queue_count": bot_state["drive_queue_count"],
        "next_post_time": next_post_iso,
        "next_post_str": next_post_str,
        "recent_logs": recent_logs
    })

@app.route("/api/trigger", methods=["POST"])
def trigger():
    bot_state["manual_trigger_requested"] = True
    bot_state["status"] = "Manual Trigger Received"
    bot_state["sub_status"] = "Processing queue immediately..."
    return jsonify({"success": True, "message": "Trigger received! Bot will process next video now."})

@app.route("/api/screenshot")
def screenshot():
    for fname in ["tiktok_published_verified.png", "tiktok_post_result.png", "tiktok_upload_err.png", "tiktok_error.png"]:
        p = config.TEMP_DIR / fname
        if p.exists():
            return send_file(str(p), mimetype="image/png")
    return jsonify({"error": "No screenshot available"}), 404

def run_web_server():
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

if __name__ == "__main__":
    run_web_server()
