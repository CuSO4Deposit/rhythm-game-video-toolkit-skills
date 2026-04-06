---
name: screen-recording-align-edit
description: Align a phone or camera recording with a direct device screen recording and render a final edited deliverable. Use this when the user has an external recording plus an internal device recording of the same session, and needs frame-accurate alignment, picture-in-picture export, or base-only export with aligned audio.
---

# Screen Recording Align Edit

Use this skill when the user has two recordings of the same session:

- an external phone or camera recording
- a direct in-device screen recording

This is not a general-purpose video editing skill. It is specifically for the workflow where one video contains the filmed device screen and the other video is the device's internal recording.

In this repository, the usual mapping is:

- `base`: the phone recording that shows the iPad and surrounding scene
- `overlay`: the direct iPad screen recording

The workflow supports two main output styles:

1. `pip_top_right_30`
   - keep the phone recording as the main video
   - place the iPad recording at `30%` size in the top-right
   - usually keep mixed audio
2. `base_only`
   - keep only the phone video
   - still align the overlay internally
   - optionally mix both audio tracks

## When To Use Which Script

If the offset is not known yet:

```bash
python scripts/align_videos.py \
  --base /path/to/phone.mp4 \
  --overlay /path/to/ipad.mp4
```

If the goal is the final edited output, prefer the end-to-end renderer:

```bash
python scripts/render_final_video.py \
  --base /path/to/phone.mp4 \
  --overlay /path/to/ipad.mp4 \
  --output /path/to/output.mp4 \
  --trim-frames <offset_frames> \
  --video-layout pip_top_right_30 \
  --audio-mode mix \
  --video-codec h264_nvenc \
  --enhance-base-clarity
```

For the phone-video-only variant with both audio tracks:

```bash
python scripts/render_final_video.py \
  --base /path/to/phone.mp4 \
  --overlay /path/to/ipad.mp4 \
  --output /path/to/output.mp4 \
  --trim-frames <offset_frames> \
  --video-layout base_only \
  --audio-mode mix \
  --video-codec h264_nvenc \
  --enhance-base-clarity
```

If the offset is not known and the user is asking for a finished video, do this:

1. run `scripts/align_videos.py`
2. read `recommended_alignment.overlay_minus_base_frames`
3. pass that value into `scripts/render_final_video.py`

## Current Render Behavior

`scripts/render_final_video.py` can currently:

- auto-estimate the offset if `--trim-frames` is omitted
- place the overlay in the top-right PiP layout
- render a base-only layout
- normalize loudness
- mix or select audio tracks
- match overlay brightness
- correct phone-video color balance
- optionally enhance phone-video clarity

## Important Constraints

- The workflow is tuned for near-matching recordings of the same event.
- It is best suited to phone-plus-screen-recording pairs, not arbitrary unrelated videos.
- It expects practical `60 fps`-style inputs.
- Timing accuracy matters; prefer the alignment script over manual guessing.
- `h264_nvenc` is supported for encoding, but simple CUDA decode is not part of the default path because the current filtergraph is CPU-filter heavy.

## Files

- `scripts/align_videos.py`
- `scripts/render_final_video.py`
- `scripts/match_brightness.py`
- `scripts/match_color_balance.py`
- `scripts/match_clarity.py`
- `scripts/match_loudness.py`

## Internal Split

If you need lower-level workflow details:

- see `skills/video-offset-align/SKILL.md` for alignment-only work
- see `skills/video-postprocess/SKILL.md` for post-alignment finishing work
