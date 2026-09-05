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

        use_anti_dup = getattr(config, "ANTI_DUPLICATE_FILTER", True)

        # Micro-crop dimensions: ensure even integers for libx264
        crop_w = int(video_w * 0.97)
        if crop_w % 2 != 0:
            crop_w -= 1
        crop_h = int(video_h * 0.97)
        if crop_h % 2 != 0:
            crop_h -= 1

        if use_anti_dup:
            logger.info("Applying Anti-Duplicate & Transformative filter (micro-zoom, color grading, 1.02x tempo, metadata stripping).")
            # Filter explanation:
            # 1. crop+scale: micro-crops edges to strip hardcoded logos and alter pixel grids
            # 2. eq: slight contrast/brightness tweak alters perceptual color histograms
            # 3. setpts+atempo: 1.02x speed shifts frame durations and audio waveforms (breaks hash match)
            # 4. overlay: positions TIME PASS logo at bottom-right
            filter_complex = (
                f"[0:v]crop={crop_w}:{crop_h},scale={video_w}:{video_h},"
                f"eq=contrast=1.02:brightness=0.01:saturation=1.03,setpts=0.98039*PTS[v0];"
                f"[1:v]scale={target_logo_w}:-1[wm];"
                f"[v0][wm]overlay=W-w-{padding}:H-h-{padding}:format=auto[outv];"
                f"[0:a]atempo=1.02[outa]"
            )
            map_args = ["-map", "[outv]", "-map", "[outa]"]
        else:
            filter_complex = (
                f"[1:v]scale={target_logo_w}:-1[wm];"
                f"[0:v][wm]overlay=W-w-{padding}:H-h-{padding}:format=auto"
            )
            map_args = []

        cmd = [
            "ffmpeg",
            "-y",                                # Overwrite destination if it exists
            "-i", str(input_video),              # Primary video stream [0]
            "-i", str(config.WATERMARK_PATH),    # Logo watermark stream [1]
            "-filter_complex", filter_complex,
        ] + map_args + [
            "-c:v", "libx264",                   # Fast, universally supported H.264
            "-preset", "fast",                   # Balance between encode speed & compression
            "-crf", "23",                        # Visually near-lossless standard for web
            "-pix_fmt", "yuv420p",               # Essential for TikTok mobile playback compatibility
            "-c:a", "aac",                       # Universal audio codec
            "-b:a", "128k",                      # Standard stereo quality
            "-movflags", "+faststart",           # Move index to head of MP4 for instant streaming
            "-map_metadata", "-1",               # Strip all camera/creator/source metadata
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
