# screen-recording-align-edit

Exploration workspace for frame-accurate alignment between:

- an iPad screen recording
- a phone recording that includes the iPad screen

The immediate target is the picture-in-picture workflow:

- keep the phone recording as the main video
- place the iPad recording at 30% size in the top-right
- preserve both audio tracks
- normalize loudness when needed
- optionally correct the phone video's color and clarity

## Current Approach

The aligner uses a two-stage strategy:

1. use full-audio correlation as the first coarse signal
2. use whole-frame visual motion only inside a small window around the audio estimate
3. detect the iPad screen by matching the direct recording content into the phone recording
4. refine again inside a small ROI window rather than rescanning the whole video

## Scripts

Extract truth from an existing Kdenlive project:

```bash
python scripts/kdenlive_truth.py /path/to/aligned-example.kdenlive
```

Run the current exploration prototype:

```bash
python scripts/explore_alignment.py \
  --base /path/to/base.mp4 \
  --overlay /path/to/overlay.mp4 \
  --detect-screen
```

Use the generic alignment entrypoint for real work:

```bash
python scripts/align_videos.py \
  --base /path/to/phone.mp4 \
  --overlay /path/to/ipad.mp4
```

Render the current end-to-end result:

```bash
python scripts/render_final_video.py \
  --base /path/to/phone.mp4 \
  --overlay /path/to/ipad.mp4 \
  --output /path/to/output.mp4 \
  --trim-frames <offset_frames> \
  --video-codec h264_nvenc \
  --enhance-base-clarity
```

`scripts/explore_alignment.py` requires `ffmpeg` and `ffprobe` on `PATH`.
When `--detect-screen` is enabled, it now does content-matched screen detection and limits ROI refinement to a small window around the coarse offset.
The coarse video pass is also windowed now, controlled by `--video-coarse-seconds` and defaulting to `24` seconds.

## Algorithm

The current aligner estimates how much the `overlay` video should be shifted relative to the `base` video.

The output is expressed as:

- `overlay_minus_base_frames`
- `overlay_minus_base_seconds`

The intended action is:

- trim that many frames from the start of the overlay
- place both clips at the same timeline start

This matches the way the sample Kdenlive project was authored.
In general terms, the returned action is to trim the head of the overlay and then align both clips at timeline start.

### 1. Audio coarse alignment

The first pass uses the audio tracks only:

- decode both audio streams to mono PCM
- apply a simple pre-emphasis filter
- compute a smoothed absolute-energy envelope
- resample that envelope to video-frame resolution
- cross-correlate the two envelope sequences

This gives a cheap coarse estimate that is usually close, but can be off by a few frames because the two devices may have different audio paths or latencies.

### 2. Windowed whole-frame visual alignment

The second pass uses frame-to-frame visual change energy:

- use the audio estimate as the center of a coarse search window
- decode only a limited video window instead of the whole file
- downscale frames
- convert to grayscale
- compute the mean absolute difference between consecutive frames
- cross-correlate the resulting change-energy sequences

This is more visually grounded than the audio-only pass and is much cheaper than scanning the entire video.

### 3. Content-matched screen detection

When `--detect-screen` is enabled, the aligner estimates the iPad screen quadrilateral inside the phone recording:

- take several frame pairs using the current coarse offset
- extract ORB features from the direct iPad recording frame and the phone frame
- match features with a Hamming-distance matcher and Lowe ratio test
- estimate a homography with RANSAC
- project the four corners of the iPad recording into the phone frame
- aggregate multiple samples and choose a stable quadrilateral

This is not generic object detection. It is content matching: the algorithm finds where the actual recorded iPad screen content appears inside the phone video.

### 4. Screen-only visual refinement

After the screen quadrilateral is known:

- warp the phone video into the detected screen region
- compare that screen-only sequence against the direct iPad recording
- restrict this pass to a small local time window around the coarse estimate
- cross-correlate the two screen-focused change-energy sequences

This usually gives the most reliable visual estimate for rhythm-game footage.

### 5. Final consensus

The final offset is chosen from all available estimates:

- audio envelope
- whole-frame visual change energy
- screen-only visual change energy, when available

If multiple methods agree on the same frame offset, that majority value wins.
Otherwise the system falls back to a score-weighted average.

This avoids letting one weaker branch pull the result away from two agreeing branches.

### Why This Works For This Use Case

This workflow is specialized for:

- two recordings of nearly the same visual event
- one recording being a direct screen capture
- the other being a camera view that contains that screen
- high timing sensitivity, such as rhythm games

It works well because:

- the audio gives a strong global anchor
- the game produces clear frame-to-frame change structure
- the direct iPad recording provides an exact visual template for detecting the screen inside the phone video

### Current Limitations

- The method assumes both videos have approximately the same frame rate in practice; the current implementation expects `60 fps` style inputs.
- The audio branch can drift by a few frames if device-specific audio latency differs.
- The screen detector depends on already having a reasonable coarse offset.
- Simple CUDA decode is not part of the default render path; the current final filtergraph is still CPU-filter heavy.

## Postprocess And Render

The repository now also includes:

- `scripts/match_brightness.py`
- `scripts/match_color_balance.py`
- `scripts/match_clarity.py`
- `scripts/match_loudness.py`
- `scripts/compose_pip.py`
- `scripts/render_final_video.py`

The current final render flow can:

- trim the overlay by the aligned offset
- either put the overlay at `30%` size in the top-right
- or keep only the base video while still using the aligned overlay audio
- preserve or mix audio with base-audio denoise plus loudness normalization
- optionally match the overlay brightness to the detected phone-screen region
- correct the base video color balance
- optionally enhance the base video clarity

Two common output modes:

- `--video-layout pip_top_right_30`
- `--video-layout base_only`

The visual-analysis helpers now share one synchronized sampling layer so brightness, color, and clarity estimation do not need three separate frame-sampling passes.

## Environment

Python dependencies are managed with `uv`.

The repository `flake.nix` includes:

- `ffmpeg`
- `mlt`
- `python314`
- `uv`

## Skill

See:

- `skills/video-offset-align/SKILL.md` for offset estimation
- `skills/video-postprocess/SKILL.md` for post-alignment finishing work such as color matching, loudness, clarity enhancement, and PiP export
