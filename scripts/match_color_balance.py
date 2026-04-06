#!/usr/bin/env python

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from video_match_sampling import aggregate, collect_synced_screen_samples


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def color_stats(frame: np.ndarray) -> dict[str, float]:
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB).astype(np.float32)
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB).astype(np.float32)
    r = rgb[:, :, 0]
    g = rgb[:, :, 1]
    b = rgb[:, :, 2]
    a = lab[:, :, 1]
    lab_b = lab[:, :, 2]
    return {
        "r_mean": float(np.mean(r)),
        "g_mean": float(np.mean(g)),
        "b_mean": float(np.mean(b)),
        "a_mean": float(np.mean(a)),
        "lab_b_mean": float(np.mean(lab_b)),
    }


def recommend_filter(
    base_stats: dict[str, float], overlay_stats: dict[str, float]
) -> dict[str, float | str]:
    red_gain = clamp(
        overlay_stats["r_mean"] / max(base_stats["r_mean"], 1e-6), 0.88, 1.12
    )
    green_gain = clamp(
        overlay_stats["g_mean"] / max(base_stats["g_mean"], 1e-6), 0.90, 1.10
    )
    blue_gain = clamp(
        overlay_stats["b_mean"] / max(base_stats["b_mean"], 1e-6), 0.88, 1.12
    )

    # Positive means base is warmer/yellower than overlay.
    warm_shift = (base_stats["lab_b_mean"] - overlay_stats["lab_b_mean"]) / 255.0
    magenta_shift = (base_stats["a_mean"] - overlay_stats["a_mean"]) / 255.0

    # Keep the correction conservative and bias toward pulling warmth out of the base.
    red_gain = clamp(
        red_gain - max(warm_shift, 0.0) * 0.10 - max(magenta_shift, 0.0) * 0.06,
        0.86,
        1.10,
    )
    blue_gain = clamp(blue_gain + max(warm_shift, 0.0) * 0.16, 0.90, 1.16)
    green_gain = clamp(green_gain - max(magenta_shift, 0.0) * 0.04, 0.90, 1.08)

    red_gain = round(red_gain, 4)
    green_gain = round(green_gain, 4)
    blue_gain = round(blue_gain, 4)

    return {
        "red_gain": red_gain,
        "green_gain": green_gain,
        "blue_gain": blue_gain,
        "warm_shift": round(warm_shift, 4),
        "magenta_shift": round(magenta_shift, 4),
        "ffmpeg_filter": f"colorchannelmixer=rr={red_gain}:gg={green_gain}:bb={blue_gain}",
    }


def match_color_balance(
    base: Path,
    overlay: Path,
    trim_frames: int,
    sample_count: int = 8,
    margin_frames: int = 600,
) -> dict:
    samples = collect_synced_screen_samples(
        base=base,
        overlay=overlay,
        trim_frames=trim_frames,
        sample_count=sample_count,
        margin_frames=margin_frames,
    )
    base_samples = [color_stats(frame) for frame in samples["base_frames"]]
    overlay_samples = [color_stats(frame) for frame in samples["overlay_frames"]]

    base_agg = aggregate(base_samples)
    overlay_agg = aggregate(overlay_samples)
    recommendation = recommend_filter(base_stats=base_agg, overlay_stats=overlay_agg)
    return {
        "base": str(base.resolve()),
        "overlay": str(overlay.resolve()),
        "trim_frames": trim_frames,
        "screen_detection": samples["screen_detection"],
        "base_screen_stats": base_agg,
        "overlay_stats": overlay_agg,
        "recommendation": recommendation,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Suggest a conservative base-video color balance correction to better match the overlay recording."
    )
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--overlay", type=Path, required=True)
    parser.add_argument("--trim-frames", type=int, required=True)
    parser.add_argument("--sample-count", type=int, default=8)
    parser.add_argument("--margin-frames", type=int, default=600)
    args = parser.parse_args()

    result = match_color_balance(
        base=args.base,
        overlay=args.overlay,
        trim_frames=args.trim_frames,
        sample_count=args.sample_count,
        margin_frames=args.margin_frames,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
