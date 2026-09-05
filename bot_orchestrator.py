"""
Main Execution Engine & Daemon Orchestrator.
Manages rate-limiting state, jitter calculation, midnight resets,
clean temporary file lifecycle, and robust exception handling.
"""

import sys
import time
import json
import random
import signal
import logging
from datetime import datetime, date, timedelta
from pathlib import Path

import config
from drive_service import DriveService
from video_processor import VideoProcessor
from tiktok_uploader import TikTokUploader

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# Setup unified logging format with dual destinations (console + file)
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(config.BASE_DIR / "bot.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("Orchestrator")


class StateManager:
    """
    Manages persistent runtime state on disk (state.json).
    Ensures that process restarts or crashes do not wipe daily posting counts.
    """
    def __init__(self, state_file: Path):
        self.state_file = state_file
        self.state = self._load_state()

    def _load_state(self) -> dict:
        today_str = date.today().isoformat()
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("current_date") == today_str:
                        return data
            except Exception as e:
                logger.warning(f"Could not parse existing state file ({e}). Initializing fresh state.")

        # If file doesn't exist or belongs to a previous date, start fresh
        fresh_state = {
            "current_date": today_str,
            "posts_today": 0,
            "last_post_timestamp": None
        }
        self._save_state(fresh_state)
        return fresh_state

    def _save_state(self, state_dict: dict) -> None:
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(state_dict, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to persist state file: {e}")

    def check_and_reset_daily(self) -> None:
        """Resets counter if current calendar date has changed."""
        today_str = date.today().isoformat()
        if self.state["current_date"] != today_str:
            logger.info(
                f"Midnight rollover detected ({self.state['current_date']} -> {today_str}). "
                f"Resetting daily counter."
            )
            self.state["current_date"] = today_str
            self.state["posts_today"] = 0
            self._save_state(self.state)

    @property
    def posts_today(self) -> int:
        self.check_and_reset_daily()
        return self.state["posts_today"]

    def record_successful_post(self) -> None:
        self.check_and_reset_daily()
        self.state["posts_today"] += 1
        self.state["last_post_timestamp"] = datetime.now().isoformat()
        self._save_state(self.state)
        logger.info(
            f"Post logged successfully. Total posted today: {self.state['posts_today']} / {config.DAILY_LIMIT}"
        )


class BotOrchestrator:
    def __init__(self):
        self.is_running = True
        self.state_mgr = StateManager(config.STATE_FILE)
        self.drive = DriveService()
        self.processor = VideoProcessor()
        self.uploader = TikTokUploader()

        # Handle graceful shutdown on Ctrl+C and kill signals
        signal.signal(signal.SIGINT, self._handle_exit)
        signal.signal(signal.SIGTERM, self._handle_exit)

    def _handle_exit(self, signum, frame):
        logger.info("Shutdown signal received. Completing active work and shutting down cleanly...")
        self.is_running = False

    def calculate_sleep_seconds(self) -> int:
        """
        Calculates interval delay: 7200 seconds (2 hours) + random anti-detection jitter.
        """
        base = config.POST_INTERVAL_SECONDS
        jitter = random.randint(config.JITTER_MIN_SECONDS, config.JITTER_MAX_SECONDS)
        total = base + jitter
        logger.info(
            f"Scheduling next execution: Base {base}s + Jitter {jitter}s = {total}s "
            f"({total // 60} minutes)"
        )
        return total

    def sleep_until_midnight(self) -> None:
        """
        Calculates exact seconds until tomorrow 00:01 AM and pauses the orchestrator.
        """
        now = datetime.now()
        tomorrow = date.today() + timedelta(days=1)
        target_midnight = datetime.combine(tomorrow, datetime.min.time()) + timedelta(seconds=60)
        seconds_to_wait = int((target_midnight - now).total_seconds())

        logger.info(
            f"Daily posting limit of {config.DAILY_LIMIT} reached for today. "
            f"Pausing orchestrator until tomorrow ({target_midnight.strftime('%Y-%m-%d %H:%M:%S')}) - "
            f"{seconds_to_wait // 3600} hours remaining."
        )
        self._interruptible_sleep(seconds_to_wait)

    def _interruptible_sleep(self, seconds: int) -> None:
        """
        Sleeps in 5-second increments so the process exits promptly if interrupted.
        """
        slept = 0
        step = 5
        while self.is_running and slept < seconds:
            time.sleep(min(step, seconds - slept))
            slept += step

    def process_single_video(self, drive_file: dict) -> bool:
        """
        Full lifecycle for a single reel:
        Download -> Watermark -> Upload -> Verify -> Delete Drive -> Clean Scratch.
        """
        file_id = drive_file["id"]
        download_id = drive_file.get("download_id", file_id)
        file_name = drive_file["name"]

        # Dedicated temporary paths for this specific job
        raw_path = config.TEMP_DIR / f"raw_{file_id}.mp4"
        processed_path = config.TEMP_DIR / f"watermarked_{file_id}.mp4"

        try:
            logger.info(f"========== Processing Pipeline Initiated: '{file_name}' ==========")

            # 1. Download raw reel from Google Drive (using target download_id)
            self.drive.download_video(download_id, raw_path)

            # 2. Apply scaled watermark and re-encode
            self.processor.apply_watermark(raw_path, processed_path)

            # 3. Direct chunk upload to TikTok and poll status
            logger.info(f"Publishing watermarked reel to TikTok...")
            upload_confirmed = self.uploader.upload_video(processed_path)

            if upload_confirmed:
                logger.info(f"Publish verified! Safe to delete source file from Google Drive.")
                # 4. Remove original from Google Drive to avoid duplicate reprocessing
                self.drive.delete_video(file_id)
                self.state_mgr.record_successful_post()
                return True
            else:
                logger.error(f"Upload was not confirmed by TikTok for '{file_name}'. Retaining Drive file.")
                return False

        except Exception as e:
            logger.error(f"Exception during processing of '{file_name}' (ID: {file_id}): {e}", exc_info=True)
            return False

        finally:
            # 5. Guaranteed local file hygiene: purge scratch files regardless of pass/fail
            for temp_file in [raw_path, processed_path]:
                if temp_file.exists():
                    try:
                        temp_file.unlink(missing_ok=True)
                        logger.debug(f"Purged local scratch file: {temp_file.name}")
                    except Exception as cleanup_err:
                        logger.warning(f"Could not purge {temp_file}: {cleanup_err}")

    def run(self) -> None:
        """
        Main continuous background loop.
        """
        logger.info("==========================================================")
        logger.info("  TikTok Automation Background Daemon Online")
        logger.info(f"  Daily Cap: {config.DAILY_LIMIT} reels/day")
        logger.info(f"  Base Interval: {config.POST_INTERVAL_SECONDS}s (2 hrs) + Anti-ban Jitter")
        logger.info(f"  Drive Folder: {config.DRIVE_FOLDER_ID}")
        logger.info("==========================================================")

        while self.is_running:
            try:
                # Check daily rate limit
                if self.state_mgr.posts_today >= config.DAILY_LIMIT:
                    self.sleep_until_midnight()
                    continue

                # Query Google Drive for the oldest reel (FIFO)
                video_file = self.drive.get_oldest_video()

                if not video_file:
                    logger.info(
                        f"No pending reels found in Google Drive. "
                        f"Re-checking in {config.EMPTY_QUEUE_SLEEP_SECONDS // 60} minutes..."
                    )
                    self._interruptible_sleep(config.EMPTY_QUEUE_SLEEP_SECONDS)
                    continue

                # Process the reel through the pipeline
                success = self.process_single_video(video_file)

                if success:
                    # Normal pacing delay with anti-detection jitter
                    interval = self.calculate_sleep_seconds()
                    logger.info(f"Waiting {interval // 60} minutes before next scheduled post...")
                    self._interruptible_sleep(interval)
                else:
                    # On single failure, back off briefly (5 min) and keep daemon alive
                    logger.warning("Job failed. Waiting 5 minutes before retrying queue...")
                    self._interruptible_sleep(300)

            except Exception as loop_err:
                logger.critical(f"Unexpected error in daemon main loop: {loop_err}", exc_info=True)
                self._interruptible_sleep(60)

        logger.info("TikTok Automation Daemon stopped.")


if __name__ == "__main__":
    bot = BotOrchestrator()
    bot.run()
