from __future__ import annotations


PIP_TOP_RIGHT = "pip_top_right"
PIP_TOP_RIGHT_LEGACY = "pip_top_right_30"
BASE_ONLY = "base_only"

PIP_LAYOUT_CHOICES = [PIP_TOP_RIGHT, PIP_TOP_RIGHT_LEGACY, BASE_ONLY]
PIP_SCALE_PERCENT_DEFAULT = 25.0


def normalize_video_layout(video_layout: str) -> str:
    if video_layout == PIP_TOP_RIGHT_LEGACY:
        return PIP_TOP_RIGHT
    return video_layout


def is_pip_layout(video_layout: str) -> bool:
    return normalize_video_layout(video_layout) == PIP_TOP_RIGHT


def resolve_scale_ratio(
    scale_ratio: float | None, pip_scale_percent: float = PIP_SCALE_PERCENT_DEFAULT
) -> float:
    if scale_ratio is not None:
        return scale_ratio
    return pip_scale_percent / 100.0
