# System Memory & Architectural Decision Record (ADR)

## State Persistence Specification (`state.json`)
The bot maintains an on-disk state file to ensure rate-limiting consistency across restarts:
```json
{
  "current_date": "2026-09-05",
  "posts_today": 3,
  "last_post_timestamp": "2026-09-05T14:22:10"
}
```
- **Rule 1**: If `datetime.now().strftime("%Y-%m-%d") != state["current_date"]`, reset `posts_today = 0` and update `current_date`.
- **Rule 2**: If `posts_today >= DAILY_LIMIT`, sleep until midnight + 60 seconds.

## FFmpeg Subprocess Philosophy
- No external heavy wrappers like `moviepy` (which leak memory on batch jobs and bundle unwanted binaries).
- Raw `subprocess.run` calls directly against `ffmpeg` and `ffprobe` binaries.
- Ensure pixel dimensions are even (`width % 2 == 0`) to prevent `x264 [error]: width not divisible by 2`.

## Cloud Transaction Integrity
1. Fetch oldest video ID from Google Drive.
2. Download to local disk.
3. Apply watermark to new output file.
4. Upload to TikTok & poll until `publish_status == "SUCCESS"`.
5. **Only upon confirmed publish**, send `service.files().delete(fileId)` to Google Drive.
6. Local scratch files deleted inside `finally` block regardless of success or failure.

## Jitter & Rate Limits
- Base interval between posts: 7200 seconds (2 hours).
- Anti-detection jitter: random delay of 60 to 600 seconds (1 to 10 minutes) added to the base interval.
- Empty queue backoff: 900 seconds (15 minutes) before re-checking Google Drive.
- Daily posting cap: Configurable between 5 and 10 reels per day.
