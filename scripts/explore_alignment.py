#!/usr/bin/env python

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path

import cv2
import numpy as np
from scipy import signal

from detect_screen_region import detect_screen_region


def require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(
            f"Required executable '{name}' was not found on PATH. "
            "Run this script inside an environment that provides ffmpeg/ffprobe."
        )
    return path


def probe_streams(path: Path) -> dict:
    ffprobe = require_tool("ffprobe")
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        str(path),
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def first_stream(data: dict, codec_type: str) -> dict:
    for stream in data["streams"]:
        if stream.get("codec_type") == codec_type:
            return stream
    raise ValueError(f"No {codec_type} stream found.")


def duration_seconds(data: dict) -> float:
    value = data.get("format", {}).get("duration")
    if value is None:
        raise ValueError("Could not read container duration.")
    return float(value)


def decode_audio_mono(path: Path, sample_rate: int = 8000) -> np.ndarray:
    ffmpeg = require_tool("ffmpeg")
    cmd = [
        ffmpeg,
        "-v",
        "error",
        "-i",
        str(path),
        "-map",
        "0:a:0",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-f",
        "f32le",
        "-acodec",
        "pcm_f32le",
        "-",
    ]
    result = subprocess.run(cmd, check=True, capture_output=True)
    audio = np.frombuffer(result.stdout, dtype=np.float32)
    if audio.size == 0:
        raise ValueError(f"Decoded empty audio stream from {path}")
    return audio


def audio_envelope(audio: np.ndarray, sample_rate: int, fps: float) -> np.ndarray:
    if audio.size < 8:
        raise ValueError("Audio is too short.")
    centered = audio - np.mean(audio)
    preemphasis = np.empty_like(centered)
    preemphasis[0] = centered[0]
    preemphasis[1:] = centered[1:] - 0.97 * centered[:-1]
    energy = np.abs(preemphasis)
    win = max(8, round(sample_rate / fps))
    kernel = np.ones(win, dtype=np.float32) / win
    smooth = np.convolve(energy, kernel, mode="same")
    step = sample_rate / fps
    positions = np.arange(0, smooth.size, step)
    frame_series = np.interp(positions, np.arange(smooth.size), smooth)
    return normalize_series(frame_series)


def decode_video_change_series(path: Path, fps: float, width: int = 160) -> np.ndarray:
    ffprobe_data = probe_streams(path)
    stream = first_stream(ffprobe_data, "video")
    src_width = int(stream["width"])
    src_height = int(stream["height"])
    height = max(8, round(src_height * (width / src_width)))
    ffmpeg = require_tool("ffmpeg")
    cmd = [
        ffmpeg,
        "-v",
        "error",
        "-i",
        str(path),
        "-map",
        "0:v:0",
        "-vf",
        f"fps={fps},scale={width}:{height},format=gray",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "-",
    ]
    result = subprocess.run(cmd, check=True, capture_output=True)
    raw = np.frombuffer(result.stdout, dtype=np.uint8)
    frame_size = width * height
    if raw.size < frame_size * 2:
        raise ValueError(f"Decoded too few frames from {path}")
    frames = raw.reshape((-1, height, width)).astype(np.float32)
    diffs = np.mean(np.abs(np.diff(frames, axis=0)), axis=(1, 2))
    return normalize_series(diffs)


def decode_video_change_series_cv2(
    path: Path,
    width: int = 160,
    quad: np.ndarray | None = None,
    start_frame: int | None = None,
    end_frame: int | None = None,
) -> np.ndarray:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video: {path}")
    source_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    source_height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if source_width <= 0 or source_height <= 0:
        raise RuntimeError(f"Could not read video size for {path}")
    start_frame = 0 if start_frame is None else max(0, int(start_frame))
    end_frame = total_frames if end_frame is None else min(total_frames, int(end_frame))
    if end_frame - start_frame < 3:
        raise ValueError(f"Window too small for change series: {path}")
    capture.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    if quad is None:
        target_height = max(8, round(source_height * width / source_width))
    else:
        widths = [
            np.linalg.norm(quad[1] - quad[0]),
            np.linalg.norm(quad[2] - quad[3]),
        ]
        heights = [
            np.linalg.norm(quad[3] - quad[0]),
            np.linalg.norm(quad[2] - quad[1]),
        ]
        quad_width = max(8, round(float(np.mean(widths))))
        quad_height = max(8, round(float(np.mean(heights))))
        target_height = max(8, round(quad_height * width / max(quad_width, 1)))
        destination = np.array(
            [
                [0, 0],
                [width - 1, 0],
                [width - 1, target_height - 1],
                [0, target_height - 1],
            ],
            dtype=np.float32,
        )
        transform = cv2.getPerspectiveTransform(quad.astype(np.float32), destination)

    diffs: list[float] = []
    prev = None
    frame_index = start_frame
    while frame_index < end_frame:
        ok, frame = capture.read()
        if not ok or frame is None:
            break
        if quad is None:
            gray = cv2.cvtColor(
                cv2.resize(frame, (width, target_height), interpolation=cv2.INTER_AREA),
                cv2.COLOR_BGR2GRAY,
            ).astype(np.float32)
        else:
            warped = cv2.warpPerspective(frame, transform, (width, target_height))
            gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY).astype(np.float32)
        if prev is not None:
            diffs.append(float(np.mean(np.abs(gray - prev))))
        prev = gray
        frame_index += 1
    capture.release()
    if len(diffs) < 2:
        raise ValueError(f"Decoded too few frames from {path}")
    return normalize_series(np.asarray(diffs, dtype=np.float32))


def alignment_window(
    coarse_lag_frames: int,
    max_lag_frames: int,
    window_frames: int,
) -> tuple[int, int, int, int]:
    pad = max_lag_frames + 4
    base_start = 0
    base_end = window_frames + pad
    overlay_start = max(0, coarse_lag_frames - pad)
    overlay_end = max(overlay_start + 4, base_end + coarse_lag_frames + pad)
    return base_start, base_end, overlay_start, overlay_end


def normalize_series(series: np.ndarray) -> np.ndarray:
    arr = np.asarray(series, dtype=np.float32)
    arr = arr - np.mean(arr)
    std = np.std(arr)
    if std < 1e-8:
        return arr
    return arr / std


def best_lag_frames(
    series_a: np.ndarray, series_b: np.ndarray, max_lag_frames: int
) -> tuple[int, float]:
    corr = signal.correlate(series_b, series_a, mode="full", method="fft")
    lags = signal.correlation_lags(series_b.size, series_a.size, mode="full")
    mask = np.abs(lags) <= max_lag_frames
    corr = corr[mask]
    lags = lags[mask]
    index = int(np.argmax(corr))
    return int(lags[index]), float(corr[index])


def best_lag_samples(
    series_a: np.ndarray, series_b: np.ndarray, max_lag_samples: int
) -> tuple[int, float]:
    corr = signal.correlate(series_b, series_a, mode="full", method="fft")
    lags = signal.correlation_lags(series_b.size, series_a.size, mode="full")
    mask = np.abs(lags) <= max_lag_samples
    corr = corr[mask]
    lags = lags[mask]
    index = int(np.argmax(corr))
    return int(lags[index]), float(corr[index])


def audio_detail_series(audio: np.ndarray) -> np.ndarray:
    if audio.size < 8:
        raise ValueError("Audio is too short.")
    centered = audio.astype(np.float32) - np.mean(audio)
    preemphasis = np.empty_like(centered)
    preemphasis[0] = centered[0]
    preemphasis[1:] = centered[1:] - 0.97 * centered[:-1]
    return normalize_series(preemphasis)


def audio_after_video_sync(
    base_audio: np.ndarray,
    overlay_audio: np.ndarray,
    video_trim_samples: int,
) -> tuple[np.ndarray, np.ndarray]:
    if video_trim_samples < 0:
        base_audio = base_audio[abs(video_trim_samples) :]
    elif video_trim_samples > 0:
        overlay_audio = overlay_audio[video_trim_samples:]
    usable = min(base_audio.size, overlay_audio.size)
    if usable < 8:
        raise ValueError("Audio overlap is too short after applying video sync.")
    return base_audio[:usable], overlay_audio[:usable]


def refine_audio_after_video_sync(
    base: Path,
    overlay: Path,
    video_trim_frames: int,
    fps: float,
    sample_rate: int = 12000,
    max_adjust_frames: float = 5.0,
    analysis_window_seconds: float = 45.0,
) -> dict:
    base_audio = decode_audio_mono(base, sample_rate=sample_rate)
    overlay_audio = decode_audio_mono(overlay, sample_rate=sample_rate)
    video_trim_samples = round(video_trim_frames / fps * sample_rate)
    synced_base, synced_overlay = audio_after_video_sync(
        base_audio,
        overlay_audio,
        video_trim_samples=video_trim_samples,
    )

    usable_samples = min(synced_base.size, synced_overlay.size)
    window_samples = round(analysis_window_seconds * sample_rate)
    if usable_samples > window_samples:
        start = max(0, (usable_samples - window_samples) // 2)
        end = start + window_samples
        synced_base = synced_base[start:end]
        synced_overlay = synced_overlay[start:end]

    base_detail = audio_detail_series(synced_base)
    overlay_detail = audio_detail_series(synced_overlay)
    max_adjust_samples = max(1, round(max_adjust_frames / fps * sample_rate))
    residual_samples, score = best_lag_samples(
        base_detail,
        overlay_detail,
        max_lag_samples=max_adjust_samples,
    )
    residual_seconds = residual_samples / sample_rate
    residual_frames = residual_seconds * fps
    return {
        "sample_rate": sample_rate,
        "analysis_window_seconds": min(
            analysis_window_seconds,
            usable_samples / sample_rate,
        ),
        "max_adjust_frames": max_adjust_frames,
        "max_adjust_samples": max_adjust_samples,
        "overlay_minus_base_samples_after_video_sync": residual_samples,
        "overlay_minus_base_seconds_after_video_sync": residual_seconds,
        "overlay_minus_base_frames_after_video_sync": residual_frames,
        "score": score,
        "base_adjustment": {
            "target": "base_audio",
            "action": (
                "delay"
                if residual_samples > 0
                else "trim_head"
                if residual_samples < 0
                else "none"
            ),
            "samples": abs(residual_samples),
            "seconds": abs(residual_seconds),
        },
    }


@dataclass
class Estimate:
    method: str
    lag_frames: int
    lag_seconds: float
    score: float
    error_vs_truth_frames: int | None = None


def consensus_lag(estimates: list[Estimate]) -> tuple[int, float]:
    buckets: dict[int, dict[str, float]] = {}
    for item in estimates:
        bucket = buckets.setdefault(item.lag_frames, {"count": 0, "score": 0.0})
        bucket["count"] += 1
        bucket["score"] += abs(item.score)
    best_lag = None
    best_key = None
    for lag, stats in buckets.items():
        key = (stats["count"], stats["score"])
        if best_key is None or key > best_key:
            best_lag = lag
            best_key = key
    assert best_lag is not None and best_key is not None
    if best_key[0] > 1:
        return int(best_lag), float(best_key[1])
    weights = [abs(item.score) for item in estimates]
    lag = round(
        sum(item.lag_frames * w for item, w in zip(estimates, weights))
        / max(sum(weights), 1e-6)
    )
    return lag, float(sum(weights))


def align_videos(
    base: Path,
    overlay: Path,
    fps: float = 60.0,
    max_lag_seconds: float = 6.0,
    truth_frames: int | None = None,
    audio_sample_rate: int = 8000,
    video_width: int = 160,
    detect_screen: bool = False,
    video_coarse_seconds: float = 24.0,
    roi_refine_seconds: float = 12.0,
) -> dict:
    probe_base = probe_streams(base)
    probe_overlay = probe_streams(overlay)
    estimates: list[Estimate] = []
    warnings: list[str] = []
    max_lag_frames = round(max_lag_seconds * fps)
    base_duration_seconds = duration_seconds(probe_base)
    overlay_duration_seconds = duration_seconds(probe_overlay)
    duration_gap_seconds = abs(base_duration_seconds - overlay_duration_seconds)
    if duration_gap_seconds > max_lag_seconds:
        warnings.append(
            "The input duration gap exceeds the current alignment search window. "
            "If these are the same session, keep the two recording start times within "
            f"{max_lag_seconds:g}s or increase --max-lag-seconds before trusting the result."
        )

    base_audio = decode_audio_mono(base, sample_rate=audio_sample_rate)
    overlay_audio = decode_audio_mono(overlay, sample_rate=audio_sample_rate)
    base_audio_env = audio_envelope(base_audio, audio_sample_rate, fps)
    overlay_audio_env = audio_envelope(overlay_audio, audio_sample_rate, fps)
    audio_lag, audio_score = best_lag_frames(
        base_audio_env, overlay_audio_env, max_lag_frames=max_lag_frames
    )
    estimates.append(
        Estimate(
            method="audio_envelope",
            lag_frames=audio_lag,
            lag_seconds=audio_lag / fps,
            score=audio_score,
            error_vs_truth_frames=None
            if truth_frames is None
            else audio_lag - truth_frames,
        )
    )

    coarse_window_frames = round(video_coarse_seconds * fps)
    coarse_base_start, coarse_base_end, coarse_overlay_start, coarse_overlay_end = (
        alignment_window(
            coarse_lag_frames=audio_lag,
            max_lag_frames=max_lag_frames,
            window_frames=coarse_window_frames,
        )
    )
    base_video_series = decode_video_change_series_cv2(
        base,
        width=video_width,
        start_frame=coarse_base_start,
        end_frame=coarse_base_end,
    )
    overlay_video_series = decode_video_change_series_cv2(
        overlay,
        width=video_width,
        start_frame=coarse_overlay_start,
        end_frame=coarse_overlay_end,
    )
    video_lag_local, video_score = best_lag_frames(
        base_video_series, overlay_video_series, max_lag_frames=max_lag_frames
    )
    video_lag = video_lag_local + (coarse_overlay_start - coarse_base_start)
    estimates.append(
        Estimate(
            method="video_change_energy",
            lag_frames=video_lag,
            lag_seconds=video_lag / fps,
            score=video_score,
            error_vs_truth_frames=None
            if truth_frames is None
            else video_lag - truth_frames,
        )
    )

    combined_lag, combined_score = consensus_lag(estimates)
    estimates.append(
        Estimate(
            method="weighted_consensus",
            lag_frames=combined_lag,
            lag_seconds=combined_lag / fps,
            score=combined_score,
            error_vs_truth_frames=None
            if truth_frames is None
            else combined_lag - truth_frames,
        )
    )

    screen_detection = None
    if detect_screen:
        coarse_lag = truth_frames if truth_frames is not None else combined_lag
        screen_detection = detect_screen_region(
            base_video=base,
            overlay_video=overlay,
            offset_frames=coarse_lag,
            sample_count=8,
            margin_frames=600,
        )
        screen_quad = np.asarray(
            screen_detection["best_candidate"]["quad_source_space"], dtype=np.float32
        )
        refine_half_window = round(roi_refine_seconds * fps / 2.0)
        base_start, base_end, overlay_start, overlay_end = alignment_window(
            coarse_lag_frames=coarse_lag,
            max_lag_frames=max_lag_frames,
            window_frames=refine_half_window * 2,
        )
        base_roi_series = decode_video_change_series_cv2(
            base,
            width=video_width,
            quad=screen_quad,
            start_frame=base_start,
            end_frame=base_end,
        )
        overlay_roi_series = decode_video_change_series_cv2(
            overlay,
            width=video_width,
            quad=None,
            start_frame=overlay_start,
            end_frame=overlay_end,
        )
        roi_lag, roi_score = best_lag_frames(
            base_roi_series, overlay_roi_series, max_lag_frames=max_lag_frames
        )
        absolute_roi_lag = roi_lag + (overlay_start - base_start)
        estimates.append(
            Estimate(
                method="detected_screen_change_energy",
                lag_frames=absolute_roi_lag,
                lag_seconds=absolute_roi_lag / fps,
                score=roi_score,
                error_vs_truth_frames=None
                if truth_frames is None
                else absolute_roi_lag - truth_frames,
            )
        )

        items = [item for item in estimates if item.method != "weighted_consensus"]
        refined_lag, refined_score = consensus_lag(items)
        estimates = items + [
            Estimate(
                method="weighted_consensus",
                lag_frames=refined_lag,
                lag_seconds=refined_lag / fps,
                score=refined_score,
                error_vs_truth_frames=None
                if truth_frames is None
                else refined_lag - truth_frames,
            )
        ]

    final_estimate = next(
        item for item in estimates if item.method == "weighted_consensus"
    )
    return {
        "base": str(base.resolve()),
        "overlay": str(overlay.resolve()),
        "fps": fps,
        "max_lag_frames": max_lag_frames,
        "warnings": warnings,
        "base_streams": {
            "video": first_stream(probe_base, "video"),
            "audio": first_stream(probe_base, "audio"),
        },
        "overlay_streams": {
            "video": first_stream(probe_overlay, "video"),
            "audio": first_stream(probe_overlay, "audio"),
        },
        "screen_detection": screen_detection,
        "video_coarse_seconds": video_coarse_seconds,
        "roi_refine_seconds": roi_refine_seconds,
        "estimates": [asdict(item) for item in estimates],
        "recommended_alignment": {
            "method": final_estimate.method,
            "overlay_minus_base_frames": final_estimate.lag_frames,
            "overlay_minus_base_seconds": final_estimate.lag_seconds,
            "action": {
                "type": "trim_overlay_head",
                "frames": final_estimate.lag_frames,
                "seconds": final_estimate.lag_seconds,
                "description": "Trim the overlay video by this amount, then align both clips at timeline start.",
            },
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Explore automatic alignment between two videos."
    )
    parser.add_argument(
        "--base", type=Path, required=True, help="Base video, e.g. phone recording."
    )
    parser.add_argument(
        "--overlay",
        type=Path,
        required=True,
        help="Overlay video, e.g. iPad recording.",
    )
    parser.add_argument("--fps", type=float, default=60.0)
    parser.add_argument("--max-lag-seconds", type=float, default=6.0)
    parser.add_argument("--truth-frames", type=int, default=None)
    parser.add_argument("--audio-sample-rate", type=int, default=8000)
    parser.add_argument("--video-width", type=int, default=160)
    parser.add_argument("--detect-screen", action="store_true")
    parser.add_argument("--video-coarse-seconds", type=float, default=24.0)
    parser.add_argument("--roi-refine-seconds", type=float, default=12.0)
    args = parser.parse_args()

    output = align_videos(
        base=args.base,
        overlay=args.overlay,
        fps=args.fps,
        max_lag_seconds=args.max_lag_seconds,
        truth_frames=args.truth_frames,
        audio_sample_rate=args.audio_sample_rate,
        video_width=args.video_width,
        detect_screen=args.detect_screen,
        video_coarse_seconds=args.video_coarse_seconds,
        roi_refine_seconds=args.roi_refine_seconds,
    )
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
