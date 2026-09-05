# Automated TikTok Video Pipeline & Publishing Daemon - Architecture Plan

## Executive Summary
Build an enterprise-grade, headless Python automation service that bridges Google Drive cloud storage with the TikTok Content Posting API v2. The service continuously ingests raw short-form video reels, applies dynamic branding via an FFmpeg filter pipeline, publishes the reels to TikTok with anti-ban rate limiting, verifies delivery, and executes two-tier garbage collection (local storage and cloud storage).
