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


def brightness_stats(frame: np.ndarray) -> dict[str, float]:
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV).astype(np.float32)
    value = hsv[:, :, 2]
    saturation = hsv[:, :, 1]
    return {
        "value_mean": float(np.mean(value)),
        "value_std": float(np.std(value)),
        "sat_mean": float(np.mean(saturation)),
    }


def recommend_eq(
    base_stats: dict[str, float], overlay_stats: dict[str, float]
) -> dict[str, float | str]:
    contrast = clamp(
        base_stats["value_std"] / max(overlay_stats["value_std"], 1e-6), 0.7, 1.4
    )
    brightness = clamp(
        (base_stats["value_mean"] - overlay_stats["value_mean"]) / 255.0, -0.12, 0.12
    )
    saturation = clamp(
        base_stats["sat_mean"] / max(overlay_stats["sat_mean"], 1e-6), 0.7, 1.4
    )
    gamma = 1.0
    return {
        "brightness": round(brightness, 4),
        "contrast": round(contrast, 4),
        "saturation": round(saturation, 4),
        "gamma": gamma,
        "ffmpeg_eq": (
            f"eq=brightness={brightness:.4f}:contrast={contrast:.4f}:"
            f"saturation={saturation:.4f}:gamma={gamma:.4f}"
        ),
    }


def match_brightness(
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
    base_samples = [brightness_stats(frame) for frame in samples["base_frames"]]
    overlay_samples = [brightness_stats(frame) for frame in samples["overlay_frames"]]

    base_agg = aggregate(base_samples)
    overlay_agg = aggregate(overlay_samples)
    recommendation = recommend_eq(base_stats=base_agg, overlay_stats=overlay_agg)
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
        description="Compare the phone-screen appearance and direct overlay recording to suggest global ffmpeg eq parameters."
    )
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--overlay", type=Path, required=True)
    parser.add_argument("--trim-frames", type=int, required=True)
    parser.add_argument("--sample-count", type=int, default=8)
    parser.add_argument("--margin-frames", type=int, default=600)
    args = parser.parse_args()

    result = match_brightness(
        base=args.base,
        overlay=args.overlay,
        trim_frames=args.trim_frames,
        sample_count=args.sample_count,
        margin_frames=args.margin_frames,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
