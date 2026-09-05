# Phase 2: Ingestion & Media Processing Pipeline

## Objectives
- Build Google Drive v3 integration with stream downloading and safe deletion.
- Build FFmpeg subprocess wrapper:
  - Probe video dimensions via `ffprobe`.
  - Calculate watermark width (`int(video_width * 0.15)`), enforce even width.
  - Scale transparent watermark logo and overlay at `(W - w - 10, H - h - 10)`.
  - Transcode with `libx264` (`-preset fast`, `-crf 23`) and `aac` (`-b:a 128k`).
- Enforce strict `try...finally` block cleanup for all temporary scratch files.

## Deliverables
- `drive_service.py`
- `video_processor.py`

## Checklist
- [ ] DriveService queries oldest file using `orderBy="createdTime asc"`.
- [ ] Chunked media download saves to `temp/raw_<file_id>.mp4`.
- [ ] FFmpeg dynamic calculation guarantees even pixel dimensions (no libx264 subsampling error).
- [ ] Watermarked reel renders cleanly without audio drift.
- [ ] Disk cleanup verified in `finally` blocks.
