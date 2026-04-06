---
name: video-offset-align
description: Given a base video and an overlay video, estimate the frame offset needed to align them, with optional content-matched screen detection for phone-plus-screen-recording workflows.
---

# Video Offset Align

Use this workflow when the task is to estimate how much one video should be shifted or trimmed to align with another video.

It is especially suited for:

- a direct screen recording
- an external camera recording that includes the screen

The current repository contains a reusable alignment skill plus lower-level exploration scripts.

## Goals

1. Take two input videos:
   - `base`: the timeline reference video
   - `overlay`: the video that should be shifted or trimmed to line up with the base
2. Estimate a frame-accurate offset using multiple signals:
   - audio envelope correlation
   - frame-to-frame visual change energy correlation in a small coarse window
   - screen-only change energy after detecting the iPad screen quadrilateral
3. Return a concrete recommended action:
   - how many frames to trim from the overlay head before aligning both clips at timeline start
4. Expose enough diagnostics to validate or debug the estimate on new video pairs.

## Files

- `scripts/align_videos.py`
- `scripts/kdenlive_truth.py`
- `scripts/explore_alignment.py`

## Prerequisites

- Python dependencies installed through `uv sync`
- `ffmpeg` and `ffprobe` on `PATH`

The repository `flake.nix` includes `ffmpeg`, so the intended environment is the project dev shell.

## Workflow

1. For normal use, run the generic aligner:

```bash
python scripts/align_videos.py \
  --base /path/to/phone.mp4 \
  --overlay /path/to/ipad.mp4
```

2. Read the result:

- `recommended_alignment.overlay_minus_base_frames`
- `recommended_alignment.overlay_minus_base_seconds`
- `recommended_alignment.action`

3. Apply the action:

- trim the overlay video by the recommended number of head frames
- start both clips together on the timeline

4. If you are validating against an already-aligned editing-project example, extract the truth from that project:

```bash
python scripts/kdenlive_truth.py /path/to/aligned-example.kdenlive
```

5. If you need the lower-level diagnostic run, use the exploration script:

```bash
python scripts/explore_alignment.py \
  --base /path/to/base.mp4 \
  --overlay /path/to/overlay.mp4 \
  --detect-screen
```

6. Compare the estimates:

- `audio_envelope`: useful coarse signal if both recordings captured the game sound faithfully
- `video_change_energy`: useful when the phone framing is stable and the screen dominates visible motion; it now runs in a small window around the audio estimate
- `detected_screen_change_energy`: uses a content-matched iPad screen quadrilateral
- `weighted_consensus`: a blend of all available signals

## Current limitations

- Screen detection currently depends on already having a coarse time offset.
- The audio method uses a simple onset-style envelope. It does not yet compensate for device-specific audio path latency.
- The skill reports the offset and recommended trim. Final rendering is handled by `video-postprocess` and `scripts/render_final_video.py`.
- CUDA acceleration is not wired in yet.

## Handoff

After offset estimation succeeds, move to `video-postprocess` for:

- picture-in-picture export
- loudness normalization and mixing
- overlay brightness matching
- base-video color-balance correction
- base-video clarity enhancement
