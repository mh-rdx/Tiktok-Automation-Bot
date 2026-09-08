"""
Google Drive API v3 Service.
Handles service account authentication, FIFO queue search, chunked download,
support for Google Drive shortcuts, and verified permanent deletion of processed videos.
"""

import os
import io
import time
import logging
from pathlib import Path
from typing import Optional, Dict, Any

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from googleapiclient.errors import HttpError

import config

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive"]


class DriveService:
    def __init__(self):
        if not config.DRIVE_FOLDER_ID:
            raise ValueError(
                "GOOGLE_DRIVE_FOLDER_ID is not configured in your .env file."
            )

        sa_json_env = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
        sa_base64_env = os.getenv("GOOGLE_SERVICE_ACCOUNT_BASE64")

        if sa_json_env:
            import json
            info = json.loads(sa_json_env)
            self.credentials = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        elif sa_base64_env:
            import base64
            import json
            info = json.loads(base64.b64decode(sa_base64_env).decode("utf-8"))
            self.credentials = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        elif config.SERVICE_ACCOUNT_FILE.exists():
            self.credentials = service_account.Credentials.from_service_account_file(
                str(config.SERVICE_ACCOUNT_FILE),
                scopes=SCOPES
            )
        else:
            raise FileNotFoundError(
                f"Google Service Account credentials not found. Provide either 'service_account.json' "
                f"or the GOOGLE_SERVICE_ACCOUNT_JSON environment variable."
            )

        self._init_service()
        logger.info("Google Drive v3 client initialized and authenticated successfully.")

    def _init_service(self):
        """Initializes or refreshes the Google Drive API client and connection pool."""
        self.service = build("drive", "v3", credentials=self.credentials, cache_discovery=False)

    def _execute_with_retry(self, request_fn, max_retries: int = 5, base_delay: float = 2.0):
        """
        Executes a Google Drive API call with automatic reconnection and retry
        for transient network errors (WinError 10054, ConnectionResetError, RemoteDisconnected, timeouts).
        """
        last_err = None
        for attempt in range(1, max_retries + 1):
            try:
                request = request_fn(self.service)
                return request.execute()
            except Exception as e:
                last_err = e
                err_str = str(e).lower()
                is_transient = any([
                    "10054" in err_str,
                    "forcibly closed" in err_str,
                    "connection reset" in err_str,
                    "remotedisconnected" in err_str,
                    "timed out" in err_str,
                    "timeout" in err_str,
                    "socket" in err_str,
                    "broken pipe" in err_str,
                    "ssl" in err_str,
                    isinstance(e, (ConnectionResetError, ConnectionError, TimeoutError, OSError))
                ])
                if isinstance(e, HttpError) and e.resp.status in (429, 500, 502, 503, 504):
                    is_transient = True

                if is_transient and attempt < max_retries:
                    delay = base_delay * (2 ** (attempt - 1))
                    logger.warning(
                        f"Transient Google Drive network glitch ({e}). "
                        f"Refreshing connection pool and retrying (attempt {attempt}/{max_retries}) in {delay:.1f}s..."
                    )
                    try:
                        self._init_service()
                    except Exception as reinit_err:
                        logger.debug(f"Service re-init notice: {reinit_err}")
                    time.sleep(delay)
                    continue
                raise last_err

    def get_oldest_video(self, exclude_ids: Optional[set] = None) -> Optional[Dict[str, Any]]:
        """
        Searches the configured Drive folder for video files or video shortcuts
        and returns the oldest valid one (FIFO).
        Validates that shortcut targets actually exist and are not trashed.
        Skips any item IDs present in exclude_ids.
        """
        exclude = exclude_ids or set()
        try:
            # Look inside folder for any non-trashed items, excluding folders
            query = f"'{config.DRIVE_FOLDER_ID}' in parents and trashed = false and mimeType != 'application/vnd.google-apps.folder'"

            results = self._execute_with_retry(
                lambda svc: svc.files().list(
                    q=query,
                    orderBy="createdTime asc",
                    pageSize=50,
                    fields="files(id, name, mimeType, size, createdTime, shortcutDetails)",
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True
                )
            )

            files = results.get("files", [])
            if not files:
                return None

            video_extensions = (".mp4", ".mov", ".mkv", ".avi", ".webm")

            for item in files:
                item_id = item.get("id")
                if item_id in exclude:
                    continue

                mime = item.get("mimeType", "")
                name = item.get("name", "").lower()

                # Google Drive Shortcut pointing to video (check this first)
                if mime == "application/vnd.google-apps.shortcut":
                    details = item.get("shortcutDetails", {})
                    target_mime = details.get("targetMimeType", "")
                    target_id = details.get("targetId")

                    if not target_id or target_id in exclude:
                        continue

                    if target_mime.startswith("video/") or name.endswith(video_extensions):
                        # Verify target file actually exists and is not trashed in Google Drive
                        try:
                            t_meta = self._execute_with_retry(
                                lambda svc: svc.files().get(
                                    fileId=target_id,
                                    fields="id, name, trashed",
                                    supportsAllDrives=True
                                )
                            )
                            if t_meta.get("trashed", False):
                                logger.warning(
                                    f"Target of shortcut '{item['name']}' ({target_id}) is in TRASH. "
                                    f"Cleaning up orphaned shortcut from queue..."
                                )
                                self.delete_video(item_id)
                                continue
                        except HttpError as t_err:
                            if t_err.resp.status in (404, 403):
                                logger.warning(
                                    f"Target of shortcut '{item['name']}' ({target_id}) is missing or inaccessible ({t_err.resp.status}). "
                                    f"Cleaning up orphaned shortcut from queue..."
                                )
                                self.delete_video(item_id)
                                continue
                            else:
                                logger.warning(f"Error checking target file {target_id}: {t_err}")

                        item["download_id"] = target_id
                        logger.info(
                            f"Found video shortcut: '{item['name']}' "
                            f"(Shortcut ID: {item['id']} -> Target Download ID: {target_id})"
                        )
                        return item

                # Direct video file
                elif mime.startswith("video/") or name.endswith(video_extensions):
                    item["download_id"] = item_id
                    logger.info(
                        f"Found direct video: '{item['name']}' "
                        f"(ID: {item['id']}, Created: {item.get('createdTime')})"
                    )
                    return item

            return None

        except Exception as e:
            logger.error(f"Google Drive query error during list query: {e}")
            raise

    def download_video(self, file_id: str, destination_path: Path) -> Path:
        """
        Streams and writes a video file from Google Drive in 10MB chunks to destination_path.
        Supports videos of any length (including 2-3 minute and long-form reels)
        with automatic reconnection on socket resets (WinError 10054).
        """
        max_attempts = 4
        for attempt in range(1, max_attempts + 1):
            try:
                logger.info(f"Downloading file ID {file_id} to {destination_path.name} (attempt {attempt}/{max_attempts})...")
                request = self.service.files().get_media(fileId=file_id, supportsAllDrives=True)

                with io.FileIO(str(destination_path), "wb") as fh:
                    downloader = MediaIoBaseDownload(fh, request, chunksize=10 * 1024 * 1024)
                    done = False
                    while not done:
                        status, done = downloader.next_chunk()
                        if status:
                            pct = int(status.progress() * 100)
                            logger.debug(f"Download progress [{destination_path.name}]: {pct}%")

                file_size_mb = destination_path.stat().st_size / (1024 * 1024)
                logger.info(f"Download finished: {destination_path.name} ({file_size_mb:.2f} MB)")
                return destination_path

            except Exception as e:
                err_str = str(e).lower()
                is_transient = any([
                    "10054" in err_str,
                    "forcibly closed" in err_str,
                    "connection" in err_str,
                    "timeout" in err_str,
                    "socket" in err_str,
                    isinstance(e, (ConnectionResetError, ConnectionError, TimeoutError, OSError))
                ])
                if is_transient and attempt < max_attempts:
                    logger.warning(f"Download stream interrupted by network glitch ({e}). Refreshing connection and retrying in 3s...")
                    try:
                        self._init_service()
                    except Exception:
                        pass
                    time.sleep(3)
                    continue

                logger.error(f"Failed while downloading file ID {file_id}: {e}")
                if destination_path.exists():
                    destination_path.unlink(missing_ok=True)
                raise

    def _get_or_create_archive_folder(self) -> str:
        """
        Gets or creates an 'Uploaded_Reels' subfolder in Google Drive to store processed items.
        """
        if hasattr(self, "_archive_folder_id") and self._archive_folder_id:
            return self._archive_folder_id

        q = f"'{config.DRIVE_FOLDER_ID}' in parents and mimeType = 'application/vnd.google-apps.folder' and name = 'Uploaded_Reels' and trashed = false"
        res = self._execute_with_retry(
            lambda svc: svc.files().list(q=q, fields="files(id, name)", supportsAllDrives=True)
        )
        files = res.get("files", [])
        if files:
            self._archive_folder_id = files[0]["id"]
            return self._archive_folder_id

        meta = {
            "name": "Uploaded_Reels",
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [config.DRIVE_FOLDER_ID]
        }
        folder = self._execute_with_retry(
            lambda svc: svc.files().create(body=meta, fields="id", supportsAllDrives=True)
        )
        self._archive_folder_id = folder.get("id")
        return self._archive_folder_id

    def delete_video(self, file_id: str) -> bool:
        """
        Moves the completed or skipped video/shortcut from the active queue folder to the 'Uploaded_Reels' folder,
        or unlinks it from the queue folder, or marks it trashed, or permanently deletes it.
        Uses automatic retry and connection recovery for all operations.
        """
        # Step 1: Attempt to move to 'Uploaded_Reels' archive subfolder
        try:
            archive_id = self._get_or_create_archive_folder()
            self._execute_with_retry(
                lambda svc: svc.files().update(
                    fileId=file_id,
                    addParents=archive_id,
                    removeParents=config.DRIVE_FOLDER_ID,
                    supportsAllDrives=True
                )
            )
            logger.info(f"Item {file_id} successfully moved to 'Uploaded_Reels' archive folder.")
            return True
        except Exception as move_err:
            logger.warning(f"Move to archive folder failed for {file_id} ({move_err}). Trying unlinking from folder...")

        # Step 2: Unlink/remove from the parent queue folder (does NOT require file ownership!)
        try:
            self._execute_with_retry(
                lambda svc: svc.files().update(
                    fileId=file_id,
                    removeParents=config.DRIVE_FOLDER_ID,
                    supportsAllDrives=True
                )
            )
            logger.info(f"Item {file_id} successfully removed/unlinked from queue folder.")
            return True
        except Exception as unlink_err:
            logger.warning(f"Unlinking {file_id} from parent folder failed ({unlink_err}). Trying trash/delete...")

        # Step 3: Attempt to mark as trashed
        try:
            self._execute_with_retry(
                lambda svc: svc.files().update(
                    fileId=file_id,
                    body={"trashed": True},
                    supportsAllDrives=True
                )
            )
            logger.info(f"Item {file_id} marked as trashed in Google Drive.")
            return True
        except Exception as trash_err:
            logger.warning(f"Trashing failed for {file_id} ({trash_err}). Trying direct permanent deletion...")

        # Step 4: Attempt direct permanent delete
        try:
            self._execute_with_retry(
                lambda svc: svc.files().delete(fileId=file_id, supportsAllDrives=True)
            )
            logger.info(f"Item {file_id} permanently deleted from Google Drive.")
            return True
        except Exception as del_err:
            logger.error(f"Could not remove {file_id} from Drive: {del_err}")
            return False
