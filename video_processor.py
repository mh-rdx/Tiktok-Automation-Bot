"""
Video Processing Pipeline using FFmpeg and FFprobe.
Inspects video dimensions, scales watermark to ~15% video width,
overlays it in the bottom-right corner with 10px padding,
and re-encodes to H.264/AAC with fast presets.
"""

import json
import logging
import subprocess
from pathlib import Path
from typing import Tuple

import config

logger = logging.getLogger(__name__)


class VideoProcessingError(Exception):
    """Raised when FFmpeg or FFprobe commands fail."""
    pass


class VideoProcessor:
    def __init__(self):
        self._verify_binaries()

    def _verify_binaries(self) -> None:
        """Verifies that ffmpeg and ffprobe are installed and discoverable on PATH."""
        # 1. Try static_ffmpeg auto-resolution if available
        try:
            import static_ffmpeg
            static_ffmpeg.add_paths()
        except Exception:
            pass

        # 2. Auto-search common Windows FFmpeg locations
        import os
        candidate_dirs = [
            r"C:\ffmpeg",
            r"C:\ffmpeg\bin",
            str(config.BASE_DIR),
        ]
        # Recursively search C:\ffmpeg if it exists
        if os.path.exists(r"C:\ffmpeg"):
            for root, dirs, files in os.walk(r"C:\ffmpeg"):
                if "ffmpeg.exe" in files:
                    candidate_dirs.append(root)

        current_path = os.environ.get("PATH", "")
        for c_dir in candidate_dirs:
            if os.path.isdir(c_dir) and c_dir not in current_path:
                os.environ["PATH"] = c_dir + os.pathsep + os.environ.get("PATH", "")

        for binary in ["ffmpeg", "ffprobe"]:
            try:
                subprocess.run(
                    [binary, "-version"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=True
                )
            except (subprocess.SubprocessError, FileNotFoundError):
                raise RuntimeError(
                    f"'{binary}' is not available in system PATH.\n"
                    f"Please install FFmpeg and verify by running '{binary} -version' in your terminal."
                )

    def get_video_dimensions(self, video_path: Path) -> Tuple[int, int]:
        """
        Uses ffprobe to extract exact video width and height.
        """
        cmd = [
            "ffprobe",
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "json",
            str(video_path)
        ]

        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True
            )
            data = json.loads(result.stdout)
            streams = data.get("streams", [])
            if not streams:
                raise VideoProcessingError(f"No video stream found in: {video_path}")

            width = int(streams[0]["width"])
            height = int(streams[0]["height"])
            logger.debug(f"Detected dimensions for {video_path.name}: {width}x{height}")
            return width, height

        except Exception as e:
            logger.error(f"Error reading video metadata with ffprobe for {video_path}: {e}")
            raise VideoProcessingError(f"ffprobe failure: {e}")

    def apply_watermark(self, input_video: Path, output_video: Path) -> Path:
        """
        Applies a transparent channel logo watermark to the bottom-right corner.

        Scaling calculation:
          - Logo width is dynamically calculated as ~15% of the video width.
          - We force target width to be an even integer (e.g. 108 -> 108, 107 -> 108)
            so libx264's yuv420p chroma subsampling doesn't fail.
          - Padding from bottom and right edges defaults to 10px.
        """
        if not config.WATERMARK_PATH.exists():
            raise FileNotFoundError(
                f"Watermark file not found at: {config.WATERMARK_PATH.resolve()}.\n"
                f"Please place your transparent logo PNG at '{config.WATERMARK_PATH}'."
            )

        video_w, video_h = self.get_video_dimensions(input_video)

        # Calculate 15% width and guarantee even integer
        target_logo_w = int(video_w * config.WATERMARK_WIDTH_RATIO)
        if target_logo_w % 2 != 0:
            target_logo_w += 1

        # Keep a sane minimum so it remains visible on low-res videos
        target_logo_w = max(24, target_logo_w)

        padding = config.WATERMARK_PADDING
        logger.info(
            f"Processing watermark on '{input_video.name}': "
            f"Base video={video_w}x{video_h}, Logo width={target_logo_w}px (15%), Padding={padding}px"
        )

        # Filter explanation:
        # [1:v]scale={w}:-1[wm] -> scales the logo to calculated width, preserving aspect ratio
        # [0:v][wm]overlay=W-w-pad:H-h-pad -> positions at bottom-right minus padding
        filter_complex = (
            f"[1:v]scale={target_logo_w}:-1[wm];"
            f"[0:v][wm]overlay=W-w-{padding}:H-h-{padding}:format=auto"
        )

        cmd = [
            "ffmpeg",
            "-y",                                # Overwrite destination if it exists
            "-i", str(input_video),              # Primary video stream [0]
            "-i", str(config.WATERMARK_PATH),    # Logo watermark stream [1]
            "-filter_complex", filter_complex,
            "-c:v", "libx264",                   # Fast, universally supported H.264
            "-preset", "fast",                   # Balance between encode speed & compression
            "-crf", "23",                        # Visually near-lossless standard for web
            "-pix_fmt", "yuv420p",               # Essential for TikTok mobile playback compatibility
            "-c:a", "aac",                       # Universal audio codec
            "-b:a", "128k",                      # Standard stereo quality
            "-movflags", "+faststart",           # Move index to head of MP4 for instant streaming
            str(output_video)
        ]

        logger.debug(f"FFmpeg command: {' '.join(cmd)}")

        process = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        if process.returncode != 0:
            # Capture the last few lines of stderr to pinpoint the error
            err_snippet = "\n".join(process.stderr.strip().splitlines()[-10:])
            logger.error(f"FFmpeg encoding failed with returncode {process.returncode}:\n{err_snippet}")
            raise VideoProcessingError(f"FFmpeg execution failed:\n{err_snippet}")

        logger.info(
            f"Watermarking and re-encoding finished successfully -> {output_video.name} "
            f"({output_video.stat().st_size / (1024 * 1024):.2f} MB)"
        )
        return output_video
