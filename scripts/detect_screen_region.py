#!/usr/bin/env python

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def order_quad(points: np.ndarray) -> np.ndarray:
    pts = np.asarray(points, dtype=np.float32)
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).reshape(-1)
    ordered = np.zeros((4, 2), dtype=np.float32)
    ordered[0] = pts[np.argmin(s)]
    ordered[2] = pts[np.argmax(s)]
    ordered[1] = pts[np.argmin(d)]
    ordered[3] = pts[np.argmax(d)]
    return ordered


def polygon_area(points: np.ndarray) -> float:
    return float(abs(cv2.contourArea(points.astype(np.float32))))


def quad_metrics(points: np.ndarray) -> dict[str, float]:
    pts = order_quad(points)
    widths = [np.linalg.norm(pts[1] - pts[0]), np.linalg.norm(pts[2] - pts[3])]
    heights = [np.linalg.norm(pts[3] - pts[0]), np.linalg.norm(pts[2] - pts[1])]
    width = float(np.mean(widths))
    height = float(np.mean(heights))
    ratio = width / max(height, 1e-6)
    return {
        "width": width,
        "height": height,
        "aspect_ratio": ratio,
        "area": polygon_area(pts),
    }


def open_video(path: Path) -> cv2.VideoCapture:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video: {path}")
    return capture


def video_info(capture: cv2.VideoCapture) -> dict[str, float]:
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


def sample_video_frames(
    path: Path, max_frames: int, target_width: int
) -> tuple[list[np.ndarray], float, tuple[int, int]]:
    capture = open_video(path)
    info = video_info(capture)
    target_height = int(round(info["height"] * target_width / info["width"]))
    indices = np.linspace(0, max(info["frames"] - 1, 0), num=max_frames, dtype=int)
    frames: list[np.ndarray] = []
    seen: set[int] = set()
    for index in indices:
        if int(index) in seen:
            continue
        seen.add(int(index))
        frame = read_frame(capture, int(index))
        if frame is None:
            continue
        frames.append(
            cv2.resize(
                frame, (target_width, target_height), interpolation=cv2.INTER_AREA
            )
        )
    capture.release()
    if len(frames) < 3:
        raise RuntimeError(f"Need at least 3 decoded frames, got {len(frames)}")
    return frames, info["fps"], (info["width"], info["height"])


def build_activity_mask(frames: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    gray_stack = np.stack(
        [cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) for frame in frames]
    ).astype(np.float32)
    mean_frame = np.mean(gray_stack, axis=0).astype(np.uint8)
    std_map = np.std(gray_stack, axis=0)
    std_map = cv2.GaussianBlur(std_map, (0, 0), 7)
    normalized = cv2.normalize(std_map, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    threshold = int(np.percentile(normalized, 82))
    _, mask = cv2.threshold(normalized, threshold, 255, cv2.THRESH_BINARY)
    kernel = np.ones((9, 9), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    return mean_frame, mask


def contour_to_quad(contour: np.ndarray) -> np.ndarray:
    rect = cv2.minAreaRect(contour)
    return order_quad(cv2.boxPoints(rect))


def candidate_quads(mean_frame: np.ndarray, activity_mask: np.ndarray) -> list[dict]:
    candidates: list[dict] = []
    contours, _ = cv2.findContours(
        activity_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < 5000:
            continue
        quad = contour_to_quad(contour)
        metrics = quad_metrics(quad)
        if metrics["aspect_ratio"] < 1.1 or metrics["aspect_ratio"] > 2.4:
            continue
        candidates.append(
            {
                "quad": quad,
                "score": metrics["area"],
                "source": "activity_mask",
                "metrics": metrics,
            }
        )

    edges = cv2.Canny(cv2.GaussianBlur(mean_frame, (5, 5), 0), 60, 140)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    mask_area = float(np.count_nonzero(activity_mask))
    for contour in contours:
        perimeter = cv2.arcLength(contour, True)
        if perimeter < 300:
            continue
        approx = cv2.approxPolyDP(contour, 0.03 * perimeter, True)
        if len(approx) != 4 or not cv2.isContourConvex(approx):
            continue
        quad = order_quad(approx.reshape(4, 2))
        metrics = quad_metrics(quad)
        if metrics["area"] < 25000:
            continue
        if metrics["aspect_ratio"] < 1.1 or metrics["aspect_ratio"] > 2.4:
            continue
        quad_mask = np.zeros_like(activity_mask)
        cv2.fillConvexPoly(quad_mask, quad.astype(np.int32), 255)
        overlap = np.count_nonzero(cv2.bitwise_and(activity_mask, quad_mask)) / max(
            mask_area, 1.0
        )
        coverage = np.count_nonzero(cv2.bitwise_and(activity_mask, quad_mask)) / max(
            np.count_nonzero(quad_mask), 1.0
        )
        score = metrics["area"] * (0.35 + overlap) * (0.35 + coverage)
        candidates.append(
            {
                "quad": quad,
                "score": float(score),
                "source": "edge_quad",
                "metrics": {
                    **metrics,
                    "activity_overlap": float(overlap),
                    "activity_coverage": float(coverage),
                },
            }
        )
    return candidates


def choose_best_candidate(candidates: list[dict], frame_shape: tuple[int, int]) -> dict:
    if not candidates:
        raise RuntimeError("No plausible screen quadrilateral was found.")
    frame_h, frame_w = frame_shape
    frame_area = frame_w * frame_h
    best = None
    best_score = None
    for item in candidates:
        metrics = item["metrics"]
        area_ratio = metrics["area"] / frame_area
        aspect_penalty = abs(metrics["aspect_ratio"] - 1.43)
        center = np.mean(item["quad"], axis=0)
        center_distance = np.linalg.norm(
            center - np.array([frame_w / 2.0, frame_h / 2.0])
        ) / max(frame_w, frame_h)
        score = (
            item["score"]
            * (1.0 - min(abs(area_ratio - 0.42), 0.35))
            * (1.0 - min(aspect_penalty / 1.2, 0.6))
        )
        score *= 1.0 - min(center_distance, 0.45)
        if best is None or score > best_score:
            best = item
            best_score = score
    assert best is not None
    best["final_score"] = float(best_score)
    return best


def scale_quad(
    quad: np.ndarray, source_size: tuple[int, int], resized_shape: tuple[int, int]
) -> np.ndarray:
    src_w, src_h = source_size
    resized_h, resized_w = resized_shape
    scale_x = src_w / resized_w
    scale_y = src_h / resized_h
    scaled = quad.copy().astype(np.float32)
    scaled[:, 0] *= scale_x
    scaled[:, 1] *= scale_y
    return scaled


def detect_activity_region(path: Path, max_frames: int, target_width: int) -> dict:
    frames, fps, source_size = sample_video_frames(
        path, max_frames=max_frames, target_width=target_width
    )
    mean_frame, activity_mask = build_activity_mask(frames)
    candidates = candidate_quads(mean_frame, activity_mask)
    best = choose_best_candidate(candidates, mean_frame.shape)
    best_resized_quad = order_quad(best["quad"])
    best_source_quad = scale_quad(
        best_resized_quad, source_size=source_size, resized_shape=mean_frame.shape
    )
    return {
        "method": "activity_region",
        "video": str(path.resolve()),
        "fps": fps,
        "source_size": {"width": source_size[0], "height": source_size[1]},
        "analysis_size": {"width": mean_frame.shape[1], "height": mean_frame.shape[0]},
        "sampled_frames": len(frames),
        "best_candidate": {
            "source": best["source"],
            "metrics": best["metrics"],
            "score": best["final_score"],
            "quad_analysis_space": best_resized_quad.round(2).tolist(),
            "quad_source_space": best_source_quad.round(2).tolist(),
        },
        "candidate_count": len(candidates),
    }


def match_screen_content(
    base_video: Path,
    overlay_video: Path,
    offset_frames: int,
    sample_count: int,
    margin_frames: int,
) -> dict:
    base_cap = open_video(base_video)
    overlay_cap = open_video(overlay_video)
    base_info = video_info(base_cap)
    overlay_info = video_info(overlay_cap)
    if abs(base_info["fps"] - overlay_info["fps"]) > 0.01:
        raise RuntimeError(
            "Base and overlay videos must have the same FPS for this prototype."
        )
    usable_frames = min(base_info["frames"], overlay_info["frames"] - offset_frames)
    start_frame = max(margin_frames, 0)
    end_frame = max(start_frame + 1, usable_frames - margin_frames)
    sample_indices = np.linspace(
        start_frame, end_frame - 1, num=sample_count, dtype=int
    )

    orb = cv2.ORB_create(5000)
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    sample_results: list[dict] = []
    overlay_corners = np.float32(
        [
            [0, 0],
            [overlay_info["width"] - 1, 0],
            [overlay_info["width"] - 1, overlay_info["height"] - 1],
            [0, overlay_info["height"] - 1],
        ]
    ).reshape(-1, 1, 2)

    for base_frame_index in sample_indices:
        overlay_frame_index = int(base_frame_index + offset_frames)
        base_frame = read_frame(base_cap, int(base_frame_index))
        overlay_frame = read_frame(overlay_cap, overlay_frame_index)
        if base_frame is None or overlay_frame is None:
            continue

        overlay_gray = cv2.cvtColor(overlay_frame, cv2.COLOR_BGR2GRAY)
        base_gray = cv2.cvtColor(base_frame, cv2.COLOR_BGR2GRAY)
        kp1, des1 = orb.detectAndCompute(overlay_gray, None)
        kp2, des2 = orb.detectAndCompute(base_gray, None)
        if des1 is None or des2 is None or len(kp1) < 20 or len(kp2) < 20:
            continue

        raw_matches = matcher.knnMatch(des1, des2, k=2)
        good = []
        for pair in raw_matches:
            if len(pair) < 2:
                continue
            m, n = pair
            if m.distance < 0.72 * n.distance:
                good.append(m)
        if len(good) < 30:
            continue

        pts1 = np.float32([kp1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
        pts2 = np.float32([kp2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
        homography, mask = cv2.findHomography(pts1, pts2, cv2.RANSAC, 5.0)
        if homography is None or mask is None or int(mask.sum()) < 40:
            continue
        projected = cv2.perspectiveTransform(overlay_corners, homography).reshape(-1, 2)
        metrics = quad_metrics(projected)
        if metrics["aspect_ratio"] < 1.1 or metrics["aspect_ratio"] > 2.4:
            continue
        sample_results.append(
            {
                "base_frame": int(base_frame_index),
                "overlay_frame": int(overlay_frame_index),
                "good_matches": len(good),
                "inliers": int(mask.sum()),
                "quad_source_space": order_quad(projected).round(2).tolist(),
                "metrics": metrics,
            }
        )

    base_cap.release()
    overlay_cap.release()
    if not sample_results:
        raise RuntimeError(
            "Content matching did not produce any valid screen quadrilaterals."
        )

    quads = np.asarray(
        [item["quad_source_space"] for item in sample_results], dtype=np.float32
    )
    median_quad = np.median(quads, axis=0)
    distances = np.mean(np.linalg.norm(quads - median_quad[None, :, :], axis=2), axis=1)
    best_index = int(np.argmin(distances))
    chosen_quad = order_quad(quads[best_index])
    metrics = quad_metrics(chosen_quad)
    return {
        "method": "content_match",
        "base_video": str(base_video.resolve()),
        "overlay_video": str(overlay_video.resolve()),
        "fps": base_info["fps"],
        "offset_frames": offset_frames,
        "base_size": {"width": base_info["width"], "height": base_info["height"]},
        "overlay_size": {
            "width": overlay_info["width"],
            "height": overlay_info["height"],
        },
        "samples_used": len(sample_results),
        "best_candidate": {
            "quad_source_space": chosen_quad.round(2).tolist(),
            "metrics": metrics,
            "score": float(np.mean([item["inliers"] for item in sample_results])),
        },
        "samples": sample_results,
    }


def detect_screen_region(
    base_video: Path,
    overlay_video: Path | None = None,
    offset_frames: int | None = None,
    max_frames: int = 24,
    target_width: int = 640,
    sample_count: int = 8,
    margin_frames: int = 600,
) -> dict:
    if overlay_video is not None and offset_frames is not None:
        return match_screen_content(
            base_video=base_video,
            overlay_video=overlay_video,
            offset_frames=offset_frames,
            sample_count=sample_count,
            margin_frames=margin_frames,
        )
    return detect_activity_region(
        base_video, max_frames=max_frames, target_width=target_width
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Detect the iPad screen quadrilateral in the phone-recorded video."
    )
    parser.add_argument("video", type=Path, help="Phone-recorded base video.")
    parser.add_argument(
        "--overlay",
        type=Path,
        default=None,
        help="Direct screen recording for content matching.",
    )
    parser.add_argument(
        "--offset-frames",
        type=int,
        default=None,
        help="Overlay start delay in frames relative to base.",
    )
    parser.add_argument("--max-frames", type=int, default=24)
    parser.add_argument("--target-width", type=int, default=640)
    parser.add_argument("--sample-count", type=int, default=8)
    parser.add_argument("--margin-frames", type=int, default=600)
    args = parser.parse_args()
    result = detect_screen_region(
        base_video=args.video,
        overlay_video=args.overlay,
        offset_frames=args.offset_frames,
        max_frames=args.max_frames,
        target_width=args.target_width,
        sample_count=args.sample_count,
        margin_frames=args.margin_frames,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
