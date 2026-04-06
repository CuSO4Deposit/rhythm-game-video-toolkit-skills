---
name: biliup-video-naming
description: Derive the final mug-style filename for a rendered video by reusing the timestamp from the source filename and asking the user only for the missing naming fields. Use this when a finished video should be renamed into the mug format expected by a biliup naming workflow.
---

# Biliup Video Naming

Use this skill after rendering, when the only remaining task is to decide the final `mug`-style filename.

This skill is intentionally narrow.

It does not try to manage upload folders or generate YAML.
It only determines the final filename.

## Scope

Assume the output should always use the `mug` naming format:

```text
<game_prefix>_YYYYMMDD_HHMMSS_<song>_<difficulty>[#<result>#][@tag1@tag2...]
```

Examples:

```text
VID_20260310_014913_はぐ_MASTER 29
VID_20260310_014913_はぐ_MASTER 29#ALL PERFECT#
VID_20260310_014913_はぐ_MASTER 29#FC#@手元
Arcaea_20260310_014913_First Snow_Future 7
```

## What To Reuse From The Source Filename

The source filename already carries the timestamp.

Reuse:

- `YYYYMMDD`
- `HHMMSS`

Do not ask the user for those again if they can be read from the source filename.

## What To Ask The User

Only ask for the missing fields needed to finalize the mug filename:

1. What game is this
2. What song name should be used
3. What difficulty text should be used
4. Whether a `#result#` segment should be added
5. Whether any `@tag` suffixes should be added

## Game Prefix Rule

The game field maps to the filename prefix like this:

- if the game is `Project SEKAI`, use `VID`
- otherwise use the game name itself as the prefix

Examples:

- `Project SEKAI` -> `VID`
- `Arcaea` -> `Arcaea`
- `vividstasis` -> `vividstasis`

## Result Rule

`#result#` is optional.

If the user does not want an explicit result marker, omit it entirely.

Examples:

- no result:
  - `VID_20260310_014913_はぐ_MASTER 29`
- with result:
  - `VID_20260310_014913_はぐ_MASTER 29#ALL PERFECT#`

## Tag Rule

`@tag` suffixes are optional.

If tags are present, append them in order:

```text
@tag1@tag2@tag3
```

If there are no tags, omit the suffix entirely.

## Practical Workflow

Given a rendered file, do this:

1. read the timestamp from the existing filename
2. ask the user only for:
   - game
   - song
   - difficulty
   - optional result
   - optional tags
3. construct the final mug filename
4. rename the video
5. if same-stem sidecar files exist, rename them to the same stem too

## Sidecar Rule

If any same-stem sidecar files exist, keep them aligned with the final stem:

- `.txt`
- `.jpg`
- `.png`

## Output Expectation

The main deliverable from this skill is one concrete final filename.

If the user also wants execution, rename:

- the video file itself
- any same-stem sidecars
