"""
Live Web Dashboard & REST Monitoring API.
Serves a modern glassmorphic dashboard on $PORT (default: 8080) for Railway.
Features:
- Live Bot Status & Uptime Monitoring
- Interactive Multi-Method TikTok Login Portal (/login):
  1. Username / Email + Password (with live 2FA verification code input)
  2. 1-Click Local PC Browser Sync (Google, Apple, or active browser session)
  3. Direct Cookie / Session ID String Paste
  4. Live TikTok QR Code Scanner
- Downloadable Local Sync scripts for Windows (.bat & .py)
"""

import os
import sys
import time
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, jsonify, render_template_string, send_file, request, redirect

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
      font-size: 14px;
      font-weight: 700;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 8px;
      transition: all 0.2s ease;
      box-shadow: 0 4px 14px rgba(254, 44, 85, 0.4);
      text-decoration: none;
    }
    .btn-trigger:hover {
      transform: translateY(-2px);
      box-shadow: 0 6px 20px rgba(254, 44, 85, 0.6);
    }
    .grid-stats {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 16px;
      margin-bottom: 24px;
    }
    .card {
      background: var(--card-bg);
      backdrop-filter: blur(10px);
      border: 1px solid var(--card-border);
      border-radius: 16px;
      padding: 20px;
      position: relative;
      overflow: hidden;
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
      color: #fff;
    }
    .card-sub {
      font-size: 12px;
      color: var(--text-muted);
      margin-top: 6px;
    }
    .progress-bar-bg {
      background: rgba(255, 255, 255, 0.08);
      border-radius: 99px;
      height: 6px;
      width: 100%;
      margin-top: 12px;
      overflow: hidden;
    }
    .progress-bar-fill {
      background: var(--accent-grad);
      height: 100%;
      width: 0%;
      border-radius: 99px;
      transition: width 0.4s ease;
    }
    .logs-panel {
      background: var(--card-bg);
      backdrop-filter: blur(12px);
      border: 1px solid var(--card-border);
      border-radius: 16px;
      padding: 20px;
    }
    .logs-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 14px;
    }
    .logs-header h3 {
      font-size: 15px;
      font-weight: 700;
      letter-spacing: 0.5px;
    }
    .logs-content {
      background: rgba(7, 9, 14, 0.85);
      border: 1px solid rgba(255, 255, 255, 0.05);
      border-radius: 10px;
      padding: 14px;
      font-family: 'JetBrains Mono', monospace;
      font-size: 12px;
      line-height: 1.6;
      color: #d1d5db;
      height: 280px;
      overflow-y: auto;
      white-space: pre-wrap;
      word-break: break-all;
    }
    footer {
      text-align: center;
      margin-top: 32px;
      font-size: 12px;
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
      <div style="display:flex; align-items:center; gap:12px;">
        <span id="account-badge" style="font-size:12px; font-weight:700; padding:6px 14px; border-radius:999px; background:rgba(255,255,255,0.08); border:1px solid rgba(255,255,255,0.15);">
          Checking TikTok...
        </span>
        <div class="live-badge">
          <span class="pulse-dot"></span>
          <span id="daemon-badge">DAEMON ONLINE</span>
        </div>
      </div>
    </header>

    <div class="banner-status">
      <div class="status-left">
        <h3>Current Bot Activity</h3>
        <p id="current-status">Checking queue...</p>
        <span id="current-substatus" style="font-size: 13px; color: var(--text-muted);"></span>
      </div>
      <div style="display:flex; gap:10px; flex-wrap:wrap; align-items:center;">
        <a href="/login" class="btn-trigger" style="background:#25f4ee; color:#07090e; box-shadow:0 4px 14px rgba(37,244,238,0.3); text-decoration:none;">
          <span>🔑</span> Connect TikTok Account
        </a>
        <button class="btn-trigger" onclick="triggerManualPost()">
          <span>🚀</span> Post Next Reel Now
        </button>
      </div>
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
      <p>TIME PASS &bull; TikTok Cloud Bot Daemon &bull; Running Standalone</p>
    </footer>
  </div>

  <script>
    let countdownInterval = null;
    let nextPostTimestamp = null;

    async function fetchStats() {
      try {
        var res = await fetch('/api/status');
        var data = await res.json();

        document.getElementById('current-status').innerText = data.status || 'Active';
        document.getElementById('current-substatus').innerText = data.sub_status || '';
        document.getElementById('uptime').innerText = data.uptime_str || '0m';
        document.getElementById('drive-queue').innerText = data.drive_queue_count + ' reels';

        var today = data.posts_today || 0;
        var limit = data.daily_limit || 10;
        document.getElementById('posts-today').innerText = today + ' / ' + limit;
        var percent = Math.min(100, Math.round((today / limit) * 100));
        document.getElementById('daily-bar').style.width = percent + '%';

        // Account badge
        var accBadge = document.getElementById('account-badge');
        if (data.tiktok_connected) {
          accBadge.innerText = '🟢 ' + (data.tiktok_user || 'TikTok Connected');
          accBadge.style.color = '#10b981';
          accBadge.style.borderColor = 'rgba(16, 185, 129, 0.4)';
          accBadge.style.background = 'rgba(16, 185, 129, 0.12)';
        } else {
          accBadge.innerHTML = '<a href="/login" style="color:#fe2c55; text-decoration:none;">🔴 Not Connected (Login)</a>';
          accBadge.style.borderColor = 'rgba(254, 44, 85, 0.4)';
          accBadge.style.background = 'rgba(254, 44, 85, 0.12)';
        }

        if (data.next_post_time) {
          nextPostTimestamp = new Date(data.next_post_time).getTime();
          document.getElementById('next-post-time').innerText = 'Target: ' + data.next_post_str;
        } else {
          nextPostTimestamp = null;
          document.getElementById('next-post-countdown').innerText = 'Queue Empty';
          document.getElementById('next-post-time').innerText = 'Add reels to Drive folder';
        }

        if (data.recent_logs && data.recent_logs.length > 0) {
          var logsView = document.getElementById('logs-view');
          var isAtBottom = logsView.scrollHeight - logsView.clientHeight <= logsView.scrollTop + 40;
          logsView.innerText = data.recent_logs.join('\\n');
          if (isAtBottom) {
            logsView.scrollTop = logsView.scrollHeight;
          }
        }
      } catch (err) {
        console.error('Fetch error:', err);
      }
    }

    function updateCountdown() {
      if (!nextPostTimestamp) return;
      var now = new Date().getTime();
      var diff = nextPostTimestamp - now;
      var el = document.getElementById('next-post-countdown');

      if (diff <= 0) {
        if (el) el.innerText = 'Due Now';
      } else {
        var hours = Math.floor(diff / (1000 * 60 * 60));
        var mins = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
        var secs = Math.floor((diff % (1000 * 60)) / 1000);
        var pad = function(n) { return n < 10 ? '0' + n : n; };
        if (el) el.innerText = pad(hours) + ':' + pad(mins) + ':' + pad(secs);
      }
    }

    async function triggerManualPost() {
      if (!confirm("Are you sure you want to trigger an immediate post right now?")) return;
      try {
        var res = await fetch('/api/trigger', { method: 'POST' });
        var data = await res.json();
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

LOGIN_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Connect TikTok Account | TIME PASS</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #07090e;
      --card-bg: #121826;
      --card-border: rgba(255, 255, 255, 0.08);
      --accent: #fe2c55;
      --accent-grad: linear-gradient(135deg, #fe2c55 0%, #25f4ee 100%);
      --cyan: #25f4ee;
      --text: #f3f4f6;
      --text-muted: #9ca3af;
      --success: #10b981;
      --warning: #f59e0b;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: radial-gradient(circle at top, #141c2e 0%, #07090e 100%);
      color: var(--text);
      font-family: 'Outfit', sans-serif;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 24px 16px;
    }
    .login-container {
      max-width: 540px;
      width: 100%;
      background: var(--card-bg);
      border: 1px solid rgba(254, 44, 85, 0.3);
      border-radius: 24px;
      padding: 32px;
      box-shadow: 0 0 60px rgba(254, 44, 85, 0.2);
    }
    .header-title {
      text-align: center;
      margin-bottom: 24px;
    }
    .header-title h1 {
      font-size: 26px;
      font-weight: 800;
      background: var(--accent-grad);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      margin-bottom: 6px;
    }
    .header-title p {
      font-size: 13px;
      color: var(--text-muted);
    }
    .tabs {
      display: flex;
      background: rgba(255, 255, 255, 0.05);
      border-radius: 14px;
      padding: 4px;
      margin-bottom: 24px;
      gap: 4px;
      overflow-x: auto;
    }
    .tab-btn {
      flex: 1;
      min-width: 90px;
      text-align: center;
      padding: 10px 8px;
      background: transparent;
      border: none;
      color: var(--text-muted);
      font-family: 'Outfit', sans-serif;
      font-size: 12px;
      font-weight: 700;
      border-radius: 10px;
      cursor: pointer;
      transition: all 0.2s ease;
      white-space: nowrap;
    }
    .tab-btn.active {
      background: var(--accent);
      color: #fff;
      box-shadow: 0 2px 10px rgba(254, 44, 85, 0.4);
    }
    .tab-pane {
      display: none;
    }
    .tab-pane.active {
      display: block;
      animation: fadeIn 0.3s ease;
    }
    @keyframes fadeIn {
      from { opacity: 0; transform: translateY(6px); }
      to { opacity: 1; transform: translateY(0); }
    }
    .form-group {
      margin-bottom: 16px;
      text-align: left;
    }
    .form-group label {
      display: block;
      font-size: 13px;
      font-weight: 600;
      color: var(--text-muted);
      margin-bottom: 6px;
    }
    .form-control {
      width: 100%;
      background: rgba(7, 9, 14, 0.8);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 12px 16px;
      font-size: 14px;
      color: #fff;
      outline: none;
      font-family: 'Outfit', sans-serif;
      transition: border 0.2s ease;
    }
    .form-control:focus {
      border-color: var(--cyan);
    }
    textarea.form-control {
      font-family: 'JetBrains Mono', monospace;
      font-size: 12px;
      resize: vertical;
      min-height: 120px;
    }
    .btn-submit {
      width: 100%;
      background: var(--accent-grad);
      color: #fff;
      border: none;
      padding: 14px;
      border-radius: 12px;
      font-size: 15px;
      font-weight: 700;
      cursor: pointer;
      transition: opacity 0.2s ease;
      margin-top: 8px;
    }
    .btn-submit:hover {
      opacity: 0.92;
    }
    .alert-box {
      border-radius: 12px;
      padding: 12px 16px;
      font-size: 13px;
      margin-top: 16px;
      display: none;
      line-height: 1.5;
    }
    .alert-info {
      background: rgba(37, 244, 238, 0.12);
      border: 1px solid rgba(37, 244, 238, 0.3);
      color: var(--cyan);
    }
    .alert-success {
      background: rgba(16, 185, 129, 0.12);
      border: 1px solid rgba(16, 185, 129, 0.3);
      color: var(--success);
    }
    .alert-error {
      background: rgba(254, 44, 85, 0.12);
      border: 1px solid rgba(254, 44, 85, 0.3);
      color: #ff6b81;
    }
    /* 2FA Card */
    .two-fa-card {
      background: rgba(37, 244, 238, 0.05);
      border: 1px solid rgba(37, 244, 238, 0.25);
      border-radius: 16px;
      padding: 18px;
      margin-top: 18px;
      display: none;
      text-align: center;
    }
    .two-fa-card h3 {
      font-size: 16px;
      color: var(--cyan);
      margin-bottom: 6px;
    }
    .two-fa-card p {
      font-size: 13px;
      color: var(--text-muted);
      margin-bottom: 14px;
    }
    .otp-input {
      font-family: 'JetBrains Mono', monospace;
      font-size: 24px;
      letter-spacing: 8px;
      text-align: center;
      width: 200px;
      padding: 10px;
      background: rgba(7, 9, 14, 0.9);
      border: 2px solid var(--cyan);
      border-radius: 12px;
      color: #fff;
      margin-bottom: 12px;
      outline: none;
    }
    /* QR View */
    .qr-view {
      text-align: center;
      padding: 10px 0;
    }
    .qr-card-box {
      background: #ffffff;
      padding: 14px;
      border-radius: 16px;
      display: inline-block;
      margin: 14px 0;
      width: 240px;
      height: 240px;
    }
    .qr-card-box img {
      width: 100%;
      height: 100%;
      object-fit: contain;
      display: block;
    }
    /* 1-Click Sync */
    .sync-card {
      background: rgba(255, 255, 255, 0.03);
      border: 1px solid var(--card-border);
      border-radius: 16px;
      padding: 20px;
      text-align: left;
    }
    .sync-card h3 {
      font-size: 16px;
      margin-bottom: 8px;
      color: #fff;
    }
    .sync-card p {
      font-size: 13px;
      color: var(--text-muted);
      line-height: 1.6;
      margin-bottom: 14px;
    }
    .sync-steps {
      font-size: 13px;
      color: #e5e7eb;
      line-height: 1.8;
      margin-bottom: 18px;
      padding-left: 18px;
    }
    .btn-download {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      background: var(--accent-grad);
      color: #fff;
      padding: 12px 20px;
      border-radius: 12px;
      font-size: 14px;
      font-weight: 700;
      text-decoration: none;
      box-shadow: 0 4px 14px rgba(254, 44, 85, 0.4);
    }
    .back-nav {
      text-align: center;
      margin-top: 20px;
    }
    .back-nav a {
      color: var(--text-muted);
      font-size: 13px;
      text-decoration: none;
    }
    .back-nav a:hover {
      color: #fff;
    }
  </style>
</head>
<body>
  <div class="login-container">
    <div class="header-title">
      <h1>Connect TikTok Account</h1>
      <p>Choose your preferred login method below</p>
    </div>

    <div class="tabs">
      <button class="tab-btn active" onclick="switchTab('email', this)">📧 Email / User</button>
      <button class="tab-btn" onclick="switchTab('cookies', this)">🍪 Paste Cookies</button>
      <button class="tab-btn" onclick="switchTab('sync', this)">💻 1-Click Sync</button>
      <button class="tab-btn" onclick="switchTab('qr', this)">📱 QR Code</button>
    </div>

    <!-- TAB 1: Email / Username + Password -->
    <div id="tab-email" class="tab-pane active">
      <div class="form-group">
        <label>Email or Username</label>
        <input type="text" id="login-identifier" class="form-control" placeholder="@rdxthedeveloper or user@gmail.com" />
      </div>
      <div class="form-group">
        <label>Password</label>
        <input type="password" id="login-password" class="form-control" placeholder="TikTok Account Password" />
      </div>
      <button id="btn-login" class="btn-submit" onclick="submitCredentials()">🚀 Sign In with TikTok</button>

      <!-- 2FA Code Prompt -->
      <div id="twofa-container" class="two-fa-card">
        <h3>🔐 Two-Step Verification Required</h3>
        <p>TikTok sent a 6-digit verification code to your email/phone. Enter it below:</p>
        <input type="text" id="twofa-code" class="otp-input" placeholder="------" maxlength="6" />
        <br>
        <button class="btn-submit" style="width: auto; padding: 10px 24px;" onclick="submit2FACode()">✅ Verify & Connect</button>
      </div>

      <div id="email-alert" class="alert-box"></div>
    </div>

    <!-- TAB 2: Paste Cookies / Session ID -->
    <div id="tab-cookies" class="tab-pane">
      <div class="form-group">
        <label>Session ID or Cookie JSON</label>
        <p style="font-size:12px; color:var(--text-muted); margin-bottom:8px;">
          Paste your <code>sessionid</code> (e.g. <code>7a8b9c...</code>) or full Cookie JSON from the Cookie-Editor extension:
        </p>
        <textarea id="cookie-input" class="form-control" placeholder='Paste sessionid or [{"name":"sessionid", "value":"..."}, ...]'></textarea>
      </div>
      <button class="btn-submit" onclick="submitCookies()">💾 Save & Connect TikTok</button>
      <div id="cookie-alert" class="alert-box"></div>
    </div>

    <!-- TAB 3: 1-Click Local PC Sync (Google, Apple, Facebook) -->
    <div id="tab-sync" class="tab-pane">
      <div class="sync-card">
        <h3>⚡ 1-Click Local PC Sync (Best for Google Logins)</h3>
        <p>
          Google OAuth actively blocks headless cloud servers, but this utility runs on your PC (where you are already logged in to TikTok Studio with Google or any method) and syncs your session directly to Railway!
        </p>
        <ol class="sync-steps">
          <li>Download the 1-click synchronizer script below.</li>
          <li>Double-click <b>sync_session.bat</b> on your computer.</li>
          <li>It connects to your browser and syncs TikTok to Railway in 3 seconds!</li>
        </ol>
        <div style="display:flex; gap:10px; flex-wrap:wrap;">
          <a href="/download/sync_session.bat" class="btn-download">⬇️ Download sync_session.bat</a>
          <a href="/download/sync_session.py" class="btn-download" style="background:#1f2937; border:1px solid rgba(255,255,255,0.1);">Download .py</a>
        </div>
      </div>
      <div id="sync-alert" class="alert-box"></div>
    </div>

    <!-- TAB 4: QR Code Scanner -->
    <div id="tab-qr" class="tab-pane">
      <div class="qr-view">
        <p style="font-size:13px; color:var(--text-muted); margin-bottom:12px; text-align:left;">
          1. Open <b>TikTok App</b> on your phone.<br>
          2. Tap <b>Profile ➔ ☰ Menu ➔ My QR Code ➔ 📷 Scan icon</b>.<br>
          3. Point camera at this QR code & tap <b>Confirm Login</b>.
        </p>
        <div class="qr-card-box">
          <img id="qr-img" src="" alt="TikTok QR Code" />
        </div>
        <div id="qr-status-txt" style="font-size:14px; font-weight:700; color:var(--cyan); margin-bottom:14px;">
          Requesting QR code...
        </div>
        <button onclick="startQr()" class="tab-btn" style="background:#1f2937; padding:8px 18px; display:inline-block;">🔄 Refresh QR</button>
      </div>
    </div>

    <div class="back-nav">
      <a href="/">← Return to Bot Dashboard</a>
    </div>
  </div>

  <script>
    let pollTimer = null;

    function switchTab(name, btn) {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
      
      var target = document.getElementById('tab-' + name);
      if (target) target.classList.add('active');
      if (btn) btn.classList.add('active');

      if (name === 'qr') {
        startQr();
      } else {
        stopQrPoll();
      }
    }

    function showAlert(boxId, type, msg) {
      var box = document.getElementById(boxId);
      if (!box) return;
      box.className = 'alert-box alert-' + type;
      box.innerText = msg;
      box.style.display = 'block';
    }

    // -------------------------------------------------------------
    // Email / Credentials Flow
    // -------------------------------------------------------------
    async function submitCredentials() {
      var id = document.getElementById('login-identifier').value.trim();
      var pw = document.getElementById('login-password').value.trim();
      if (!id || !pw) {
        showAlert('email-alert', 'error', 'Please enter your username/email and password.');
        return;
      }

      showAlert('email-alert', 'info', 'Connecting to TikTok and submitting credentials...');
      document.getElementById('btn-login').disabled = true;

      try {
        var resp = await fetch('/api/login/credentials', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({identifier: id, password: pw})
        });
        var data = await resp.json();
        handleAuthStatus(data);
        startStatusPoll();
      } catch (e) {
        showAlert('email-alert', 'error', 'Request failed: ' + e);
        document.getElementById('btn-login').disabled = false;
      }
    }

    async function submit2FACode() {
      var code = document.getElementById('twofa-code').value.trim();
      if (!code || code.length < 4) {
        showAlert('email-alert', 'error', 'Please enter a valid verification code.');
        return;
      }
      showAlert('email-alert', 'info', 'Verifying code with TikTok...');

      try {
        var resp = await fetch('/api/login/verify-2fa', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({code: code})
        });
        var data = await resp.json();
        handleAuthStatus(data);
      } catch (e) {
        showAlert('email-alert', 'error', 'Error submitting code: ' + e);
      }
    }

    function handleAuthStatus(d) {
      if (d.status === 'waiting_for_2fa' || d.is_2fa_required) {
        document.getElementById('twofa-container').style.display = 'block';
        showAlert('email-alert', 'info', 'TikTok sent a 6-digit code. Please enter it above.');
      } else if (d.status === 'authenticated') {
        showAlert('email-alert', 'success', '🎉 Successfully logged in as ' + (d.user || 'TikTok User') + '! Redirecting...');
        setTimeout(() => { window.location.href = '/'; }, 2000);
      } else if (d.status === 'error') {
        showAlert('email-alert', 'error', d.error || 'Login failed. Try Cookie Paste or Local Sync.');
        document.getElementById('btn-login').disabled = false;
      } else if (d.status === 'logging_in') {
        showAlert('email-alert', 'info', d.info || 'Submitting credentials to TikTok...');
      }
    }

    function startStatusPoll() {
      if (pollTimer) clearInterval(pollTimer);
      pollTimer = setInterval(async () => {
        try {
          var r = await fetch('/api/login/status');
          var d = await r.json();
          handleAuthStatus(d);
          if (d.status === 'authenticated' || d.status === 'error') {
            clearInterval(pollTimer);
          }
        } catch(e) {}
      }, 2000);
    }

    // -------------------------------------------------------------
    // Cookie Flow
    // -------------------------------------------------------------
    async function submitCookies() {
      var raw = document.getElementById('cookie-input').value.trim();
      if (!raw) {
        showAlert('cookie-alert', 'error', 'Please paste your sessionid or cookie JSON.');
        return;
      }
      showAlert('cookie-alert', 'info', 'Verifying session with TikTok Studio...');

      try {
        var resp = await fetch('/api/login/paste-cookies', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({cookies: raw})
        });
        var data = await resp.json();
        if (data.success) {
          showAlert('cookie-alert', 'success', '🎉 ' + data.message + ' Redirecting to dashboard...');
          setTimeout(() => { window.location.href = '/'; }, 2000);
        } else {
          showAlert('cookie-alert', 'error', data.error || 'Cookies were rejected or expired.');
        }
      } catch (e) {
        showAlert('cookie-alert', 'error', 'Error: ' + e);
      }
    }

    // -------------------------------------------------------------
    // QR Flow
    // -------------------------------------------------------------
    let qrTimer = null;
    async function startQr() {
      document.getElementById('qr-status-txt').innerText = 'Generating TikTok QR code...';
      try {
        var resp = await fetch('/api/qr/start', {method: 'POST'});
        var data = await resp.json();
        updateQrUI(data);
      } catch(e) {}

      if (qrTimer) clearInterval(qrTimer);
      qrTimer = setInterval(async () => {
        try {
          var r = await fetch('/api/qr/status');
          var d = await r.json();
          updateQrUI(d);
          if (d.status === 'authenticated') {
            clearInterval(qrTimer);
            document.getElementById('qr-status-txt').innerText = '🎉 Login Confirmed! Redirecting...';
            document.getElementById('qr-status-txt').style.color = '#10b981';
            setTimeout(() => { window.location.href = '/'; }, 2000);
          }
        } catch(e) {}
      }, 2000);
    }

    function updateQrUI(d) {
      if (d.qr_image && d.qr_image.length > 50) {
        document.getElementById('qr-img').src = d.qr_image;
      }
      if (d.status === 'waiting_for_qr' || d.status === 'waiting_for_scan') {
        document.getElementById('qr-status-txt').innerText = 'Waiting for TikTok app scan...';
        document.getElementById('qr-status-txt').style.color = '#25f4ee';
      } else if (d.status === 'expired') {
        document.getElementById('qr-status-txt').innerText = '⚠️ QR Expired. Click Refresh QR.';
        document.getElementById('qr-status-txt').style.color = '#f59e0b';
      }
    }

    function stopQrPoll() {
      if (qrTimer) clearInterval(qrTimer);
    }

    // Check URL query parameters for active tab (?tab=qr or ?tab=sync)
    window.addEventListener('DOMContentLoaded', () => {
      var params = new URLSearchParams(window.location.search);
      var tabParam = params.get('tab');
      if (tabParam) {
        var btn = Array.from(document.querySelectorAll('.tab-btn')).find(b => b.innerText.toLowerCase().includes(tabParam.toLowerCase()));
        if (btn) switchTab(tabParam, btn);
      }
    });
  </script>
</body>
</html>
"""

# -----------------------------------------------------------------
# Flask Routes
# -----------------------------------------------------------------

@app.route("/")
def index():
    return render_template_string(DASHBOARD_HTML)


@app.route("/login")
def login_portal():
    return render_template_string(LOGIN_HTML)


@app.route("/qr")
def qr_redirect():
    return redirect("/login?tab=qr")


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

    # Check TikTok authentication status
    session_file = config.BASE_DIR / "tiktok_session.json"
    tiktok_connected = session_file.exists() or bool(getattr(config, "TIKTOK_COOKIES_JSON", None)) or bool(getattr(config, "TIKTOK_SESSION_ID", None))
    tiktok_user = "@rdxthedeveloper" if tiktok_connected else None

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
        "recent_logs": recent_logs,
        "tiktok_connected": tiktok_connected,
        "tiktok_user": tiktok_user
    })


@app.route("/api/trigger", methods=["POST"])
def trigger():
    bot_state["manual_trigger_requested"] = True
    bot_state["status"] = "Manual Trigger Received"
    bot_state["sub_status"] = "Processing queue immediately..."
    return jsonify({"success": True, "message": "Trigger received! Bot will process next video now."})


@app.route("/api/screenshot")
def screenshot():
    for fname in ["tiktok_published_verified.png", "tiktok_post_result.png", "tiktok_upload_err.png", "tiktok_error.png", "login_qr.png"]:
        p = config.TEMP_DIR / fname
        if p.exists():
            return send_file(str(p), mimetype="image/png")
    return jsonify({"error": "No screenshot available"}), 404


@app.route("/api/screenshot/qr")
def qr_screenshot():
    p = config.TEMP_DIR / "login_qr.png"
    if p.exists():
        return send_file(str(p), mimetype="image/png")
    return jsonify({"error": "No QR screenshot found"}), 404


# -----------------------------------------------------------------
# Multi-Method Auth API Routes
# -----------------------------------------------------------------

@app.route("/api/login/credentials", methods=["POST"])
def login_credentials():
    from auth_manager import TikTokAuthManager
    data = request.get_json() or {}
    identifier = data.get("identifier", "").strip()
    password = data.get("password", "").strip()
    if not identifier or not password:
        return jsonify({"status": "error", "error": "Username and password required"}), 400

    manager = TikTokAuthManager()
    res = manager.start_credentials_login(identifier, password)
    return jsonify(res)


@app.route("/api/login/verify-2fa", methods=["POST"])
def verify_2fa():
    from auth_manager import TikTokAuthManager
    data = request.get_json() or {}
    code = data.get("code", "").strip()
    if not code:
        return jsonify({"error": "Verification code is required"}), 400

    manager = TikTokAuthManager()
    res = manager.submit_2fa_code(code)
    return jsonify(res)


@app.route("/api/login/paste-cookies", methods=["POST"])
def paste_cookies():
    from auth_manager import TikTokAuthManager
    data = request.get_json() or {}
    raw_cookies = data.get("cookies", "").strip()
    if not raw_cookies:
        return jsonify({"success": False, "error": "Cookie content cannot be empty"}), 400

    manager = TikTokAuthManager()
    res = manager.save_and_verify_cookies(raw_cookies)
    return jsonify(res)


@app.route("/api/login/status")
def login_status():
    from auth_manager import TikTokAuthManager
    manager = TikTokAuthManager()
    return jsonify(manager.get_status())


@app.route("/api/qr/start", methods=["POST", "GET"])
def qr_start():
    from auth_manager import TikTokAuthManager
    manager = TikTokAuthManager()
    res = manager.start_qr_login()
    return jsonify(res)


@app.route("/api/qr/status")
def qr_status():
    from auth_manager import TikTokAuthManager
    manager = TikTokAuthManager()
    return jsonify(manager.get_status())


@app.route("/api/session/upload", methods=["POST"])
def session_upload():
    """Receives JSON session export from sync_session.py."""
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "No JSON payload provided"}), 400

    session_file = config.BASE_DIR / "tiktok_session.json"
    try:
        with open(session_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        from auth_manager import TikTokAuthManager
        manager = TikTokAuthManager()
        raw_str = json.dumps(data)
        manager.save_and_verify_cookies(raw_str)

        return jsonify({"success": True, "message": "Session received and verified successfully!"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/download/sync_session.bat")
def download_bat():
    bat_file = config.BASE_DIR / "sync_session.bat"
    if bat_file.exists():
        return send_file(str(bat_file), as_attachment=True, download_name="sync_session.bat")
    return jsonify({"error": "File not found"}), 404


@app.route("/download/sync_session.py")
def download_py():
    py_file = config.BASE_DIR / "sync_session.py"
    if py_file.exists():
        return send_file(str(py_file), as_attachment=True, download_name="sync_session.py")
    return jsonify({"error": "File not found"}), 404


def run_web_server():
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    run_web_server()
