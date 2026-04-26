---
name: screen-recording-align-edit
description: Align a phone or camera recording with a direct device screen recording and render a final edited deliverable. Use this when the user has an external recording plus an internal device recording of the same session, and needs frame-accurate alignment, picture-in-picture export, or base-only export with aligned audio.
---

# Screen Recording Align Edit

Use this skill when the user has two recordings of the same session:

- an external phone or camera recording
- a direct in-device screen recording

This is not a general-purpose video editing skill. It is specifically for the workflow where one video contains the filmed device screen and the other video is the device's internal recording.

Before running any repository script or final ffmpeg render command, enter this repository's `nix develop` shell so the project-provided toolchain, Python environment, and codec behavior are used consistently.

Do not run the main workflow from the plain system shell unless the user explicitly asks for that fallback.

In this repository, the usual mapping is:

- `base`: the phone recording that shows the iPad and surrounding scene
- `overlay`: the direct iPad screen recording

The workflow supports two main output styles:

1. `pip_top_right`
   - keep the phone recording as the main video
   - place the iPad recording at `25%` size in the top-right by default
   - usually keep mixed audio
2. `base_only`
   - keep only the phone video
   - still align the overlay internally
   - optionally mix both audio tracks

## Default Task Routing From Folder Contents

When the user gives you task folders instead of describing the edit mode explicitly, infer the default workflow from the folder contents and naming metadata:

- if the task folder contains exactly one video file, treat it as a single-video cleanup task
- the default single-video workflow is conservative base-video audio denoise plus loudness normalization at `60 fps`
- if the task folder contains exactly two video files, treat it as a phone-plus-screen-recording alignment task
- for two-file tasks, first run the full alignment workflow and keep the weighted-consensus result unless that full path fails
- for two-file tasks, if the metadata indicates `初见` or `初见标签` and the result is not `AP` or `PM`, default to `pip_top_right`
- for other two-file tasks, including `AP` or `PM`, default to `base_only`

This default routing is only for cases where the user did not specify a different output style explicitly.

## Required Intake Before Rendering

When the user is asking for a finished deliverable, collect the naming metadata up front instead of waiting until after render.

Ask proactively for:

1. game
2. song name
3. difficulty text
4. score or result text
5. optional `@tag` suffixes

Naming rule to keep in mind during intake:

- if the result is `AP` or `PM`, do not emit a `#result#` segment in the final filename
- other result texts such as score strings remain eligible for `#result#`

For `Arcaea`, the practical defaults to ask for are:

- game: `Arcaea`
- song name, for example `Regenade`
- difficulty, for example `Future 9+`
- score or play result text, for example `13-4`
- tags, for example `@初见`

If the user already supplied some of these fields, reuse them and only ask for the missing ones.
Keep these values available for the later naming step.

## When To Use Which Script

If the offset is not known yet:

```bash
nix develop -c python scripts/align_videos.py \
  --base /path/to/phone.mp4 \
  --overlay /path/to/ipad.mp4
```

If already inside the dev shell, use:

```bash
python scripts/align_videos.py \
  --base /path/to/phone.mp4 \
  --overlay /path/to/ipad.mp4
```

If the goal is the final edited output, prefer the end-to-end renderer:

```bash
nix develop -c python scripts/render_final_video.py \
  --base /path/to/phone.mp4 \
  --overlay /path/to/ipad.mp4 \
  --output /path/to/output.mp4 \
  --trim-frames <offset_frames> \
  --fps 60 \
  --video-layout pip_top_right \
  --audio-mode mix \
  --video-codec h264_nvenc \
  --hwaccel cuda \
  --enhance-base-clarity
```

If already inside the dev shell, use:

```bash
python scripts/render_final_video.py \
  --base /path/to/phone.mp4 \
  --overlay /path/to/ipad.mp4 \
  --output /path/to/output.mp4 \
  --trim-frames <offset_frames> \
  --fps 60 \
  --video-layout pip_top_right \
  --audio-mode mix \
  --video-codec h264_nvenc \
  --hwaccel cuda \
  --enhance-base-clarity
```

For the phone-video-only variant with both audio tracks:

```bash
nix develop -c python scripts/render_final_video.py \
  --base /path/to/phone.mp4 \
  --overlay /path/to/ipad.mp4 \
  --output /path/to/output.mp4 \
  --trim-frames <offset_frames> \
  --fps 60 \
  --video-layout base_only \
  --audio-mode mix \
  --video-codec h264_nvenc \
  --hwaccel cuda \
  --enhance-base-clarity
```

If already inside the dev shell, use:

```bash
python scripts/render_final_video.py \
  --base /path/to/phone.mp4 \
  --overlay /path/to/ipad.mp4 \
  --output /path/to/output.mp4 \
  --trim-frames <offset_frames> \
  --fps 60 \
  --video-layout base_only \
  --audio-mode mix \
  --video-codec h264_nvenc \
  --hwaccel cuda \
  --enhance-base-clarity
```

If the offset is not known and the user is asking for a finished video, do this:

1. collect missing naming metadata first
2. run `scripts/align_videos.py`
3. keep the full multi-estimate result and do not skip the weighted-consensus step
4. read `recommended_alignment.overlay_minus_base_frames`
5. pass that value into `scripts/render_final_video.py`

## Alignment Policy

Default to the full alignment workflow.

- Run the normal `scripts/align_videos.py` path first so audio, full-frame video change, detected-screen change, and `weighted_consensus` all participate.
- Do not shortcut to audio-only alignment or skip majority voting just to save time.
- Treat `recommended_alignment.overlay_minus_base_frames` from the completed consensus result as the default render offset.
- Only fall back to `--no-screen-detect` or other reduced-confidence shortcuts if the full alignment path fails or the user explicitly asks for a faster approximation.
- If a fallback path is used, say so clearly.

## Offset Disagreement Policy

Large disagreement between methods is a warning sign, not a normal case.

Expected behavior for near-matching phone-plus-screen recordings:

- audio, video-change, detected-screen-change, and weighted-consensus should usually cluster very tightly
- in practical good cases, expect the methods to land within about `3 frames`

When the methods do not cluster tightly, do not proceed straight to final render as if the result were trustworthy.

Treat any of the following as a manual-review trigger:

- the non-consensus methods disagree with each other by more than `3 frames`
- `weighted_consensus` differs from any strong constituent estimate by more than `3 frames`
- the full path fails and you must fall back to `--no-screen-detect`
- the estimated offset changes sign between methods
- one method is a clear outlier relative to the others

When a manual-review trigger happens:

1. stop before the final deliverable render
2. tell the user that the offset estimates disagree unusually strongly
3. present the per-method offsets explicitly
4. generate review media so the user can choose the correct candidate offset

Preferred review media:

- default to a short comparison video, not a single still image
- use a `5` to `8` second clip around a visually busy section with clear note timing, taps, judgments, lane movement, or other high-temporal-detail moments
- generate one short candidate clip per plausible offset so the user can compare them side by side or one after another
- only use still-image snapshots as a fallback when video generation is too expensive or the disagreement is already down to a tiny neighborhood

Default tooling for review clips:

```bash
nix develop -c python scripts/generate_offset_review_clips.py \
  --base /path/to/base.mp4 \
  --overlay /path/to/overlay.mp4 \
  --output-dir /path/to/review-clips \
  --offset 84 \
  --offset 87 \
  --offset 88 \
  --start 45 \
  --duration 6 \
  --fps 60 \
  --video-layout pip_top_right \
  --audio-mode mix \
  --video-codec h264_nvenc
```

If already inside the dev shell, use:

```bash
python scripts/generate_offset_review_clips.py \
  --base /path/to/base.mp4 \
  --overlay /path/to/overlay.mp4 \
  --output-dir /path/to/review-clips \
  --offset 84 \
  --offset 87 \
  --offset 88 \
  --start 45 \
  --duration 6 \
  --fps 60 \
  --video-layout pip_top_right \
  --audio-mode mix \
  --video-codec h264_nvenc
```

Candidate selection policy for review clips:

- always include the `weighted_consensus` offset
- include each materially different method offset
- if several methods are within `1` to `2` frames of each other, collapse them to one representative candidate
- if the plausible neighborhood is narrow, also include nearby `+/- 1` frame candidates around the leading choice

After the user chooses a candidate offset:

- use that exact chosen offset for the final render
- mention clearly that the final render is using a manually confirmed offset

## Current Render Behavior

`scripts/render_final_video.py` can currently:

- auto-estimate the offset if `--trim-frames` is omitted
- place the overlay in the top-right PiP layout
- render a base-only layout
- normalize loudness
- mix or select audio tracks
- apply a default `80 Hz` highpass on the `base` audio before denoise and loudness normalization
- when `--audio-mode mix` is used, refine the remaining base-versus-overlay audio offset after video sync and compensate it on the base track before mixing
- match overlay brightness
- correct phone-video color balance
- optionally enhance phone-video clarity
- render at `60 fps` via `--fps 60`
- use `h264_nvenc` with `-cq 22 -b:v 0`
- use `--hwaccel cuda` when the environment supports it

## Preferred Encode Policy

For final delivery, prefer the following render defaults unless the user requests otherwise:

- output fps: `60`
- layout: `pip_top_right` when the user wants PiP
- audio mode: `mix`
- base video remains the main canvas
- keep the default `80 Hz` base-audio highpass enabled unless the user explicitly wants the raw low-frequency content preserved
- keep residual mixed-audio refinement enabled unless the user explicitly asks to preserve the raw uncorrected mixed timing

Codec selection policy:

- first check whether the environment can use CUDA/NVENC
- perform that check from inside `nix develop`, not from the plain system shell
- if CUDA is available, prefer `--video-codec h264_nvenc --hwaccel cuda`
- if CUDA is not available, fall back to `--video-codec libx264`
- keep the NVENC quality target at `-cq 22` as implemented by `scripts/render_final_video.py`

Residual mixed-audio refinement policy:

- treat the final video sync offset as the source of truth for picture alignment
- after that sync point is fixed, allow `scripts/render_final_video.py` to estimate the small remaining audio-only offset in a narrow neighborhood
- this refinement is intended for device-specific audio-path latency differences that remain even when the pictures are perfectly aligned
- the current implementation applies the correction only to the `base` audio track before `amix`
- if needed, disable it with `--no-audio-sync-refine`

Base-audio cleanup policy:

- before denoise and loudness normalization, the current default render path applies `highpass=f=80` to the `base` audio
- this is meant to remove low-frequency environmental noise such as HVAC rumble, handling vibration, and desk resonance
- the default denoise stage remains `afftdn=nf=-28:om=o`
- if needed, disable the highpass with `--no-base-audio-highpass`

## Important Constraints

- The workflow is tuned for near-matching recordings of the same event.
- It is best suited to phone-plus-screen-recording pairs, not arbitrary unrelated videos.
- It expects practical `60 fps`-style inputs.
- Timing accuracy matters; prefer the alignment script over manual guessing.
- `h264_nvenc` is supported for encoding, and `--hwaccel cuda` should be preferred when the environment supports it.
- Even when using CUDA/NVENC, keep the final output target at `60 fps`.

## Files

- `scripts/align_videos.py`
- `scripts/render_final_video.py`
- `scripts/generate_offset_review_clips.py`
- `scripts/match_brightness.py`
- `scripts/match_color_balance.py`
- `scripts/match_clarity.py`
- `scripts/match_loudness.py`

## Internal Split

If you need lower-level workflow details:

- see `skills/video-offset-align/SKILL.md` for alignment-only work
- see `skills/video-postprocess/SKILL.md` for post-alignment finishing work
