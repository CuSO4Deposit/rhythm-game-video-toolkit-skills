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


def clarity_stats(frame: np.ndarray) -> dict[str, float]:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV).astype(np.float32)

    lap_var = float(cv2.Laplacian(gray, cv2.CV_32F).var())
    sobel_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    sobel_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    grad_mag = np.sqrt(sobel_x * sobel_x + sobel_y * sobel_y)
    edge_mean = float(np.mean(grad_mag))

    blurred = cv2.GaussianBlur(gray, (0, 0), 1.2)
    noise_residual = gray - blurred
    noise_std = float(np.std(noise_residual))

    value = hsv[:, :, 2]
    sat = hsv[:, :, 1]
    return {
        "laplacian_var": lap_var,
        "edge_mean": edge_mean,
        "noise_std": noise_std,
        "value_mean": float(np.mean(value)),
        "value_std": float(np.std(value)),
        "sat_mean": float(np.mean(sat)),
    }


def recommend_filter_chain(
    base_stats: dict[str, float], overlay_stats: dict[str, float]
) -> dict[str, float | str]:
    sharpness_ratio = overlay_stats["laplacian_var"] / max(
        base_stats["laplacian_var"], 1e-6
    )
    edge_ratio = overlay_stats["edge_mean"] / max(base_stats["edge_mean"], 1e-6)
    noise_ratio = base_stats["noise_std"] / max(overlay_stats["noise_std"], 1e-6)
    sat_ratio = overlay_stats["sat_mean"] / max(base_stats["sat_mean"], 1e-6)
    contrast_ratio = overlay_stats["value_std"] / max(base_stats["value_std"], 1e-6)

    use_denoise = noise_ratio > 1.05
    denoise_luma = round(clamp((noise_ratio - 1.0) * 3.0, 0.0, 4.0), 3)
    denoise_chroma = round(clamp(denoise_luma * 0.75, 0.0, 3.0), 3)

    unsharp_amount = round(clamp((sharpness_ratio - 1.0) * 1.1, 0.2, 1.8), 3)
    cas_strength = round(clamp((edge_ratio - 1.0) * 0.6, 0.0, 0.45), 3)
    contrast = round(clamp(contrast_ratio, 0.9, 1.25), 4)
    saturation = round(clamp(sat_ratio, 0.95, 1.35), 4)

    filters: list[str] = []
    if use_denoise and denoise_luma > 0.0:
        filters.append(
            f"hqdn3d=luma_spatial={denoise_luma}:chroma_spatial={denoise_chroma}:"
            f"luma_tmp={max(0.0, denoise_luma * 0.6):.3f}:chroma_tmp={max(0.0, denoise_chroma * 0.6):.3f}"
        )
    filters.append(f"unsharp=lx=5:ly=5:la={unsharp_amount}:cx=3:cy=3:ca=0.0")
    if cas_strength > 0.0:
        filters.append(f"cas=strength={cas_strength}")
    if contrast != 1.0 or saturation != 1.0:
        filters.append(f"eq=contrast={contrast}:saturation={saturation}")

    return {
        "sharpness_ratio": round(sharpness_ratio, 4),
        "edge_ratio": round(edge_ratio, 4),
        "noise_ratio": round(noise_ratio, 4),
        "recommended_unsharp_amount": unsharp_amount,
        "recommended_cas_strength": cas_strength,
        "recommended_contrast": contrast,
        "recommended_saturation": saturation,
        "recommended_denoise_luma": denoise_luma,
        "ffmpeg_filter_chain": ",".join(filters),
    }


def match_clarity(
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
    base_samples = [clarity_stats(frame) for frame in samples["base_frames"]]
    overlay_samples = [clarity_stats(frame) for frame in samples["overlay_frames"]]

    base_agg = aggregate(base_samples)
    overlay_agg = aggregate(overlay_samples)
    recommendation = recommend_filter_chain(base_agg, overlay_agg)
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
        description="Suggest a phone-video enhancement chain that makes the base video look closer to the overlay recording."
    )
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--overlay", type=Path, required=True)
    parser.add_argument("--trim-frames", type=int, required=True)
    parser.add_argument("--sample-count", type=int, default=8)
    parser.add_argument("--margin-frames", type=int, default=600)
    args = parser.parse_args()

    result = match_clarity(
        base=args.base,
        overlay=args.overlay,
        trim_frames=args.trim_frames,
        sample_count=args.sample_count,
        margin_frames=args.margin_frames,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
