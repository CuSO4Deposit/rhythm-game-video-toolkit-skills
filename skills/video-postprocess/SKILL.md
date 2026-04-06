---
name: video-postprocess
description: Post-alignment finishing workflow for brightness matching, loudness matching, base-video color and clarity correction, and picture-in-picture composition after the offset between two videos is already known.
---

# Video Postprocess

Use this workflow after the alignment step has already produced a reliable offset.

This skill is deliberately orthogonal to `video-offset-align`:

- `video-offset-align` estimates how much to trim or shift
- `video-postprocess` makes the aligned output look and sound correct

## Scope

This skill currently covers these finishing tasks:

1. brightness and basic color matching
2. loudness normalization and mixing strategy
3. picture-in-picture composition
4. clarity enhancement for the base video
5. color-balance correction for the base video

## Assumptions

- the base video is the main visual track, usually the phone recording
- the overlay video is the direct iPad recording
- the overlay has already been trimmed by the alignment offset
- both clips now start together on the timeline

## Recommended Architecture

Treat each task as a separate stage:

1. alignment
2. visual finishing
3. audio finishing
4. final composition/export

Do not mix these concerns into one monolithic command until each stage is stable.

## 1. Brightness Matching

Goal:

- make the inserted iPad recording look less jarring relative to the phone footage

Shortest viable route:

- measure the overlay appearance against the screen region seen in the phone recording
- apply lightweight corrections first:
  - brightness
  - contrast
  - saturation
  - gamma

Practical ffmpeg route:

- `eq` for:
  - `brightness`
  - `contrast`
  - `saturation`
  - `gamma`

Escalation path if `eq` is not enough:

- `colorbalance`
- `curves`
- `colorlevels`

Suggested engineering approach:

1. sample a few synchronized frames
2. compare luminance statistics between:
   - the detected phone-screen region
   - the direct iPad recording
3. solve for a conservative correction
4. apply one global correction for the full clip

Avoid per-frame brightness chasing in the first version. It will look unstable.

## 1.5 Base Video Color Balance

Goal:

- pull the phone video closer to the direct iPad recording when the phone footage looks too warm, yellow, or otherwise tinted

Current route:

- compare synchronized screen-region color statistics between:
  - the warped phone-screen region
  - the direct iPad recording
- derive conservative per-channel gains
- apply them globally to the base video

Practical ffmpeg route:

- `colorchannelmixer`

Current helper:

```bash
python scripts/match_color_balance.py \
  --base /path/to/phone.mp4 \
  --overlay /path/to/ipad.mp4 \
  --trim-frames <offset_frames>
```

What it returns:

- synchronized color statistics
- a conservative global base-video color-balance correction

## 2. Loudness Matching

There are two likely output modes:

- use only the iPad audio
- keep both audio tracks

For stable output, use EBU R128 style normalization.

Practical ffmpeg route:

- `loudnorm`
- optionally `ebur128` for diagnostics

Recommended workflow:

1. measure the audio stream with a first `loudnorm` pass using `print_format=json`
2. run a second pass with the measured values filled back in
3. normalize each stream to the chosen target

If both tracks are kept:

- normalize each stream first
- then mix with `amix`
- then optionally apply a gentle limiter or another final `loudnorm`

Do not start with arbitrary `volume=` multipliers as the main solution. They are useful only for quick manual overrides.

## 3. Picture-in-Picture Composition

Goal:

- keep the phone recording as main
- place the iPad recording at 30% size in the top-right

Practical ffmpeg route:

- `scale`
- `overlay`
- optionally `format`, `pad`, `setsar`

Canonical filtergraph shape:

```text
[overlay] scale=main_w*0.3:-1 [pip];
[base][pip] overlay=x=W-w-margin:y=margin
```

Notes:

- compute the scaled width from the main output size
- preserve aspect ratio by using `-1` for the scaled height
- add a consistent margin from the top-right corner

If the iPad clip should have a subtle frame or shadow, that should be added as a later visual polish layer, not in the first version.

## Suggested First Deliverables

Build these as separate scripts or subcommands:

1. `match_brightness`
   - input: base video, overlay video, detected screen quad
   - output: recommended visual correction parameters

2. `match_loudness`
   - input: one or two audio/video files
   - output: measured loudness stats and normalization parameters

3. `compose_pip`
   - input: aligned base + aligned overlay
   - output: final PiP video

4. `match_clarity`
   - input: base video, overlay video, aligned offset
   - output: a conservative enhancement chain for the base video

5. `match_color_balance`
   - input: base video, overlay video, aligned offset
   - output: a conservative base-video color-balance correction

6. `render_final_video`
   - input: base video, overlay video, aligned offset
   - output: final rendered PiP video

This decomposition keeps the system debuggable.

Current script:

```bash
python scripts/compose_pip.py \
  --base /path/to/phone.mp4 \
  --overlay /path/to/ipad.mp4 \
  --output /path/to/output.mp4 \
  --trim-frames <offset_frames>
```

Current end-to-end render script:

```bash
python scripts/render_final_video.py \
  --base /path/to/phone.mp4 \
  --overlay /path/to/ipad.mp4 \
  --output /path/to/output.mp4 \
  --trim-frames <offset_frames> \
  --video-codec h264_nvenc \
  --enhance-base-clarity
```

Defaults:

- overlay scale ratio: `0.30`
- position: top-right
- margin: `48`
- audio mode: `mix`

Loudness helper:

```bash
python scripts/match_loudness.py /path/to/file1.mp4 /path/to/file2.mp4
```

What it returns:

- measured loudness stats for each input
- a reusable second-pass `loudnorm` filter string for each input

Brightness helper:

```bash
python scripts/match_brightness.py \
  --base /path/to/phone.mp4 \
  --overlay /path/to/ipad.mp4 \
  --trim-frames <offset_frames>
```

What it returns:

- screen-matched brightness statistics
- a conservative global `ffmpeg eq` suggestion

Clarity helper:

```bash
python scripts/match_clarity.py \
  --base /path/to/phone.mp4 \
  --overlay /path/to/ipad.mp4 \
  --trim-frames <offset_frames>
```

What it returns:

- synchronized sharpness and edge statistics
- a conservative base-video enhancement chain such as:
  - `unsharp`
  - `cas`
  - optional small `eq` correction

Final renderer behavior:

- applies base-video color-balance correction by default
- optionally applies base-video clarity enhancement with `--enhance-base-clarity`
- applies overlay brightness matching by default
- applies loudness normalization by default
- supports two visual layouts:
  - `pip_top_right_30`
  - `base_only`

Implementation note:

- the current visual-analysis helpers share one synchronized sampling layer so final rendering does not need to repeat screen detection and frame reads separately for brightness, color, and clarity

## Current Preferred Tools

- `ffmpeg` for composition, normalization, and rendering
- `ffprobe` for stream metadata
- Python for orchestration and parameter estimation

## Risks

- visual matching can become overfit if color correction is too aggressive
- dual-audio output can sound muddy if both normalized streams are mixed without policy
- PiP output will look wrong if brightness and loudness are not handled first

## Current Default Advice

- If the offset is already known, prefer `scripts/render_final_video.py`.
- Use `--video-layout pip_top_right_30` for the current PiP style.
- Use `--video-layout base_only --audio-mode mix` when you want only the phone video but both audio tracks.
- If the phone video looks too warm or yellow, keep base color matching enabled.
- If the phone video looks soft compared with the overlay, add `--enhance-base-clarity`.
- Use `h264_nvenc` when available, but do not assume CUDA decode alone will speed up the current CPU-heavy filtergraph.
