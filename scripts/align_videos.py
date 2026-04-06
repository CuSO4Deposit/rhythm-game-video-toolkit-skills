#!/usr/bin/env python

from __future__ import annotations

import argparse
import json
from pathlib import Path

from explore_alignment import align_videos


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Given a base video and an overlay video, estimate how much the overlay should be shifted to align."
    )
    parser.add_argument(
        "--base",
        type=Path,
        required=True,
        help="Base video, usually the phone recording.",
    )
    parser.add_argument(
        "--overlay",
        type=Path,
        required=True,
        help="Overlay video, usually the direct iPad recording.",
    )
    parser.add_argument("--max-lag-seconds", type=float, default=12.0)
    parser.add_argument("--video-coarse-seconds", type=float, default=24.0)
    parser.add_argument("--roi-refine-seconds", type=float, default=12.0)
    parser.add_argument("--video-width", type=int, default=160)
    parser.add_argument("--audio-sample-rate", type=int, default=8000)
    parser.add_argument("--no-screen-detect", action="store_true")
    args = parser.parse_args()

    result = align_videos(
        base=args.base,
        overlay=args.overlay,
        max_lag_seconds=args.max_lag_seconds,
        video_coarse_seconds=args.video_coarse_seconds,
        roi_refine_seconds=args.roi_refine_seconds,
        video_width=args.video_width,
        audio_sample_rate=args.audio_sample_rate,
        detect_screen=not args.no_screen_detect,
    )

    summary = {
        "base": result["base"],
        "overlay": result["overlay"],
        "recommended_alignment": result["recommended_alignment"],
        "estimates": result["estimates"],
        "screen_detection": result["screen_detection"],
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
