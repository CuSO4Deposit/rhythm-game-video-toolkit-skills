#!/usr/bin/env python

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from detect_screen_region import detect_screen_region


def open_video(path: Path) -> cv2.VideoCapture:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video: {path}")
    return capture


def video_meta(capture: cv2.VideoCapture) -> dict[str, float]:
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if width <= 0 or height <= 0 or fps <= 0 or frames <= 0:
        raise RuntimeError("Could not read video metadata.")
    return {"width": width, "height": height, "fps": fps, "frames": frames}


def read_frame(capture: cv2.VideoCapture, frame_index: int) -> np.ndarray | None:
    capture.set(cv2.CAP_PROP_POS_FRAMES, int(frame_index))
    ok, frame = capture.read()
    if not ok or frame is None:
        return None
    return frame


def warp_screen_region(
    base_frame: np.ndarray, quad: np.ndarray, output_size: tuple[int, int]
) -> np.ndarray:
    out_w, out_h = output_size
    destination = np.array(
        [[0, 0], [out_w - 1, 0], [out_w - 1, out_h - 1], [0, out_h - 1]],
        dtype=np.float32,
    )
    transform = cv2.getPerspectiveTransform(quad.astype(np.float32), destination)
    return cv2.warpPerspective(base_frame, transform, (out_w, out_h))


def aggregate(samples: list[dict[str, float]]) -> dict[str, float]:
    keys = samples[0].keys()
    return {key: float(np.mean([sample[key] for sample in samples])) for key in keys}


def collect_synced_screen_samples(
    base: Path,
    overlay: Path,
    trim_frames: int,
    sample_count: int = 8,
    margin_frames: int = 600,
) -> dict:
    screen_detection = detect_screen_region(
        base_video=base,
        overlay_video=overlay,
        offset_frames=trim_frames,
        sample_count=sample_count,
        margin_frames=margin_frames,
    )
    quad = np.asarray(
        screen_detection["best_candidate"]["quad_source_space"], dtype=np.float32
    )

    base_cap = open_video(base)
    overlay_cap = open_video(overlay)
    base_info = video_meta(base_cap)
    overlay_info = video_meta(overlay_cap)

    usable_frames = min(base_info["frames"], overlay_info["frames"] - trim_frames)
    start_frame = max(margin_frames, 0)
    end_frame = max(start_frame + 1, usable_frames - margin_frames)
    indices = np.linspace(start_frame, end_frame - 1, num=sample_count, dtype=int)

    base_frames: list[np.ndarray] = []
    overlay_frames: list[np.ndarray] = []
    output_size = (overlay_info["width"], overlay_info["height"])

    for base_frame_index in indices:
        overlay_frame_index = int(base_frame_index + trim_frames)
        base_frame = read_frame(base_cap, int(base_frame_index))
        overlay_frame = read_frame(overlay_cap, overlay_frame_index)
        if base_frame is None or overlay_frame is None:
            continue
        base_screen = warp_screen_region(base_frame, quad=quad, output_size=output_size)
        base_frames.append(base_screen)
        overlay_frames.append(overlay_frame)

    base_cap.release()
    overlay_cap.release()

    if not base_frames or not overlay_frames:
        raise RuntimeError("Could not collect synchronized frame samples.")

    return {
        "screen_detection": screen_detection,
        "base_frames": base_frames,
        "overlay_frames": overlay_frames,
    }
