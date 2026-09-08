"""
Video Processing Pipeline using FFmpeg and FFprobe.
Inspects video dimensions, scales watermark to ~15% video width,
overlays it in the bottom-right corner with 10px padding,
and re-encodes to H.264/AAC with fast presets.
"""

import json
import math
import logging
import subprocess
from pathlib import Path
from typing import Tuple, Dict, Any

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

    def get_video_info(self, video_path: Path) -> Dict[str, Any]:
        """
        Uses ffprobe to extract video width, height, exact duration, and audio presence.
        Supports any video duration and format.
        """
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "stream=codec_type,width,height,duration",
            "-show_entries", "format=duration",
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
            video_streams = [s for s in streams if s.get("codec_type") == "video"]
            if not video_streams:
                raise VideoProcessingError(f"No video stream found in: {video_path}")

            width = int(video_streams[0].get("width", 720))
            height = int(video_streams[0].get("height", 1280))

            # Duration detection from format container or video stream
            raw_dur = data.get("format", {}).get("duration") or video_streams[0].get("duration") or 0.0
            try:
                duration = float(raw_dur)
            except (ValueError, TypeError):
                duration = 0.0

            has_audio = any(s.get("codec_type") == "audio" for s in streams)

            logger.info(
                f"Inspected '{video_path.name}': {width}x{height}, "
                f"duration={duration:.2f}s, has_audio={has_audio}"
            )
            return {
                "width": width,
                "height": height,
                "duration": duration,
                "has_audio": has_audio
            }

        except Exception as e:
            logger.error(f"Error reading video metadata with ffprobe for {video_path}: {e}")
            raise VideoProcessingError(f"ffprobe failure: {e}")

    def get_video_dimensions(self, video_path: Path) -> Tuple[int, int]:
        """
        Backwards-compatible helper returning width and height.
        """
        info = self.get_video_info(video_path)
        return info["width"], info["height"]

    def apply_watermark(self, input_video: Path, output_video: Path) -> Path:
        """
        Applies a transparent channel logo watermark to the bottom-right corner.
        Supports videos of ANY duration:
          - Automatically loops ultra-short clips (< 3.0s) so they meet TikTok's minimum length requirement.
          - Clamps ultra-long videos (> 600s / 10 mins) so they meet TikTok's web maximum limit.
          - Robust against missing audio tracks (synthesizes clean stereo AAC).
          - Applies transformative anti-duplicate zoom/tempo/metadata alterations.
        """
        if not config.WATERMARK_PATH.exists():
            raise FileNotFoundError(
                f"Watermark file not found at: {config.WATERMARK_PATH.resolve()}.\n"
                f"Please place your transparent logo PNG at '{config.WATERMARK_PATH}'."
            )

        info = self.get_video_info(input_video)
        video_w = info["width"]
        video_h = info["height"]
        duration = info["duration"]
        has_audio = info["has_audio"]

        # Calculate 15% width and guarantee even integer for libx264
        target_logo_w = int(video_w * config.WATERMARK_WIDTH_RATIO)
        if target_logo_w % 2 != 0:
            target_logo_w += 1
        target_logo_w = max(24, target_logo_w)

        padding = config.WATERMARK_PADDING
        logger.info(
            f"Processing watermark on '{input_video.name}': "
            f"Base video={video_w}x{video_h}, Logo width={target_logo_w}px (15%), "
            f"Duration={duration:.2f}s, Audio={has_audio}, Padding={padding}px"
        )

        # 1. Handle any duration:
        # TikTok Studio requires videos to be between 3 seconds and 10 minutes (600 seconds)
        loop_args = []
        if 0 < duration < 3.0:
            loops = math.ceil(3.5 / duration) - 1
            logger.info(
                f"Short video detected ({duration:.2f}s < 3.0s limit). "
                f"Auto-looping {loops + 1}x to meet TikTok minimum length (>= 3.5s)."
            )
            loop_args = ["-stream_loop", str(loops)]

        clamp_args = []
        if duration > 600.0:
            logger.warning(
                f"Video duration is {duration:.2f}s (> 600s). "
                f"Clamping to 599s to satisfy TikTok's 10-minute web upload limit."
            )
            clamp_args = ["-t", "599"]

        # 2. Audio handling for any duration / missing audio
        if has_audio:
            audio_filter = "[0:a]atempo=1.02[outa]"
            map_audio = ["-map", "[outa]"]
        else:
            logger.info("No audio track detected. Synthesizing silent stereo AAC stream for full TikTok compatibility.")
            audio_filter = "anullsrc=r=44100:cl=stereo[outa]"
            map_audio = ["-map", "[outa]", "-shortest"]

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
            filter_complex = (
                f"[0:v]crop={crop_w}:{crop_h},scale={video_w}:{video_h},"
                f"eq=contrast=1.02:brightness=0.01:saturation=1.03,setpts=0.98039*PTS[v0];"
                f"[1:v]scale={target_logo_w}:-1[wm];"
                f"[v0][wm]overlay=W-w-{padding}:H-h-{padding}:format=auto[outv];"
                f"{audio_filter}"
            )
        else:
            if has_audio:
                filter_complex = (
                    f"[1:v]scale={target_logo_w}:-1[wm];"
                    f"[0:v][wm]overlay=W-w-{padding}:H-h-{padding}:format=auto[outv]"
                )
                map_audio = ["-map", "0:a"]
            else:
                filter_complex = (
                    f"[1:v]scale={target_logo_w}:-1[wm];"
                    f"[0:v][wm]overlay=W-w-{padding}:H-h-{padding}:format=auto[outv];"
                    f"anullsrc=r=44100:cl=stereo[outa]"
                )
                map_audio = ["-map", "[outa]", "-shortest"]

        cmd = [
            "ffmpeg",
            "-y",                                # Overwrite destination if it exists
        ] + loop_args + [
            "-i", str(input_video),              # Primary video stream [0]
            "-i", str(config.WATERMARK_PATH),    # Logo watermark stream [1]
            "-filter_complex", filter_complex,
            "-map", "[outv]",
        ] + map_audio + clamp_args + [
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
