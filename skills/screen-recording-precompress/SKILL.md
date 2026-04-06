---
name: screen-recording-precompress
description: Normalize phone recordings and direct screen recordings to a common 60 fps compressed MP4 staging area before alignment. Use this when raw inputs should be precompressed into consistent 60 fps MP4 files before running the alignment and render tools.
---

# Screen Recording Precompress

Use this skill before alignment when the source videos are still in the raw staging area and should first be normalized into compressed `60 fps` MP4 files.

Use the bundled script in this repository:

- `scripts/precompress_videos.py`

## Goal

Take raw video files from an input directory and produce normalized files in an output directory.

The bundled precompress step:

- scans an input directory for common video files
- emits `.mp4` files into the chosen output directory
- defaults to `60 fps`
- first tries CUDA decode plus NVENC
- then falls back to CPU decode plus NVENC
- finally falls back to CPU decode plus `libx264`

## Normal Workflow

Run the bundled script:

```bash
python scripts/precompress_videos.py \
  --input-dir /path/to/raw \
  --output-dir /path/to/compressed \
  --fps 60
```

## Expected Output

For an input such as:

- `VID_20260310_014913.mp4`
- `ScreenRecording_03-10-2026 01-49-09_1_2.MOV`

expect normalized outputs such as:

- `/path/to/compressed/VID_20260310_014913.mp4`
- `/path/to/compressed/ScreenRecording_03-10-2026 01-49-09_1_2.mp4`

The alignment and final-render skills should generally prefer these normalized outputs over the raw recordings.

## Failure Handling

Raw ffmpeg CUDA decode can fail with CUDA-related decode or thread/resource issues.

The bundled script already retries in this order:

1. CUDA decode plus `h264_nvenc`
2. CPU decode plus `h264_nvenc`
3. CPU decode plus `libx264`

## What To Check

After preprocessing:

- both files exist in the output directory
- both files report `60 fps`
- filenames still match the original stems closely enough for later pairing

## Handoff

After successful preprocessing, continue with:

- `skills/screen-recording-align-edit/SKILL.md`
