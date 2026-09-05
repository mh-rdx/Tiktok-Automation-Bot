# Phase 3: Scheduling, Rate Limiting & TikTok Upload

## Objectives
- Implement TikTok API v2 chunked upload:
  - Step 1: `/v2/post/publish/video/init/` to get `upload_url` & `publish_id`.
  - Step 2: Binary chunk PUT transfer with `Content-Range` headers (10MB chunks).
  - Step 3: `/v2/post/publish/status/fetch/` polling for verified confirmation.
- Persistent state tracking via `state.json`:
  - Daily counter, current date, last post timestamp.
  - Automatic midnight reset.
- Anti-detection interval engine:
  - Base interval: 7200s (2 hours).
  - Random jitter: 60s to 600s (1 to 10 minutes).
  - Empty queue handler: 900s (15 minutes).

## Deliverables
- `tiktok_uploader.py`
- `bot_orchestrator.py`

## Checklist
- [ ] Direct Post chunking conforms to TikTok 5MB-64MB constraints.
- [ ] Polling logic handles `PROCESSING_UPLOAD`, `SUCCESS`, and `FAILED` gracefully.
- [ ] State persistence survives process restarts.
- [ ] Jitter delay prevents strict bot footprint.
- [ ] Drive deletion executes ONLY after TikTok returns confirmed success.
