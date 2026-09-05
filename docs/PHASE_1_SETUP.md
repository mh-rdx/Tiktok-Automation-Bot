# Phase 1: Authentication & Dependencies Setup

## Objectives
- Initialize Python virtual environment with dependencies.
- Provision Google Cloud Project & Service Account for Drive v3.
- Obtain TikTok Content Posting API v2 Access Token & OpenID.
- Verify FFmpeg and FFprobe system availability.

## Deliverables
- `requirements.txt`
- `.env.example`
- `config.py`

## Checklist
- [ ] Install FFmpeg (`ffmpeg -version` & `ffprobe -version` must pass).
- [ ] Create `service_account.json` in Google Cloud Console.
- [ ] Share target Google Drive folder with the Service Account email (`Editor` role).
- [ ] TikTok Developer App configured with `video.upload` and `video.publish` scopes.
- [ ] `.env` created and validated by running `python -c "import config"`.
