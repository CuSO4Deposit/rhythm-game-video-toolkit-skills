#!/usr/bin/env python

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


def require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"Required executable '{name}' was not found on PATH.")
    return path


def encoder_args(video_codec: str) -> list[str]:
    if video_codec == "libx264":
        return ["-c:v", "libx264", "-preset", "medium", "-crf", "18"]
    if video_codec == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "22", "-b:v", "0"]
    raise ValueError(f"Unsupported video codec: {video_codec}")


def parse_offsets(raw_offsets: list[str]) -> list[int]:
    values: list[int] = []
    for item in raw_offsets:
        for part in item.split(","):
            part = part.strip()
            if not part:
                continue
            values.append(int(part))
    if not values:
        raise ValueError("At least one offset must be provided.")
    # Preserve order while deduplicating.
    return list(dict.fromkeys(values))


def sanitize_offset_label(offset: int) -> str:
    if offset > 0:
        return f"plus_{offset}f"
    if offset < 0:
        return f"minus_{abs(offset)}f"
    return "zero_0f"


def seek_times(
    start_seconds: float, offset_frames: int, fps: float
) -> tuple[float, float]:
    offset_seconds = offset_frames / fps
    if offset_frames >= 0:
        return start_seconds, start_seconds + offset_seconds
    return start_seconds + abs(offset_seconds), start_seconds


def build_filter_complex(
    video_layout: str,
    scale_ratio: float,
    margin: int,
    offset_frames: int,
    label: str,
    audio_mode: str,
) -> str:
    drawtext = (
        "drawtext="
        "fontcolor=white:"
        "fontsize=36:"
        "box=1:"
        "boxcolor=black@0.65:"
        "boxborderw=12:"
        "x=40:"
        "y=40:"
        f"text='{label} | offset={offset_frames}f'"
    )

    if video_layout == "pip_top_right_30":
        video = (
            f"[1:v]scale=iw*{scale_ratio}:ih*{scale_ratio}[pip];"
            f"[0:v][pip]overlay=x=W-w-{margin}:y={margin},{drawtext}[vout]"
        )
    elif video_layout == "base_only":
        video = f"[0:v]{drawtext}[vout]"
    else:
        raise ValueError(f"Unsupported video layout: {video_layout}")

    if audio_mode == "base":
        audio = "[0:a]anull[aout]"
    elif audio_mode == "overlay":
        audio = "[1:a]anull[aout]"
    elif audio_mode == "mix":
        audio = "[0:a]anull[a0];[1:a]anull[a1];[a0][a1]amix=inputs=2:normalize=0[aout]"
    else:
        raise ValueError(f"Unsupported audio mode: {audio_mode}")

    return f"{video};{audio}"


def render_candidate(
    ffmpeg_bin: str,
    base: Path,
    overlay: Path,
    output_path: Path,
    offset_frames: int,
    fps: float,
    start_seconds: float,
    duration_seconds: float,
    video_layout: str,
    audio_mode: str,
    video_codec: str,
    scale_ratio: float,
    margin: int,
) -> None:
    base_seek, overlay_seek = seek_times(start_seconds, offset_frames, fps)
    label = output_path.stem
    filter_complex = build_filter_complex(
        video_layout=video_layout,
        scale_ratio=scale_ratio,
        margin=margin,
        offset_frames=offset_frames,
        label=label,
        audio_mode=audio_mode,
    )

    cmd = [
        ffmpeg_bin,
        "-y",
        "-ss",
        f"{base_seek:.6f}",
        "-t",
        f"{duration_seconds:.6f}",
        "-i",
        str(base),
        "-ss",
        f"{overlay_seek:.6f}",
        "-t",
        f"{duration_seconds:.6f}",
        "-i",
        str(overlay),
        "-filter_complex",
        filter_complex,
        "-map",
        "[vout]",
        "-map",
        "[aout]",
        "-r",
        f"{fps:.6f}",
        *encoder_args(video_codec),
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-shortest",
        str(output_path),
    ]
    subprocess.run(cmd, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate short review clips for multiple candidate alignment offsets."
    )
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--overlay", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--offset",
        dest="offsets",
        action="append",
        required=True,
        help="Candidate offset in frames. Repeat or use comma-separated values.",
    )
    parser.add_argument("--start", type=float, default=30.0)
    parser.add_argument("--duration", type=float, default=6.0)
    parser.add_argument("--fps", type=float, default=60.0)
    parser.add_argument(
        "--video-layout",
        choices=["pip_top_right_30", "base_only"],
        default="pip_top_right_30",
    )
    parser.add_argument(
        "--audio-mode",
        choices=["base", "overlay", "mix"],
        default="mix",
    )
    parser.add_argument(
        "--video-codec",
        choices=["libx264", "h264_nvenc"],
        default="h264_nvenc",
    )
    parser.add_argument("--scale-ratio", type=float, default=0.30)
    parser.add_argument("--margin", type=int, default=48)
    args = parser.parse_args()

    ffmpeg_bin = require_tool("ffmpeg")
    offsets = parse_offsets(args.offsets)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    for offset_frames in offsets:
        filename = f"candidate_{sanitize_offset_label(offset_frames)}.mp4"
        output_path = args.output_dir / filename
        render_candidate(
            ffmpeg_bin=ffmpeg_bin,
            base=args.base,
            overlay=args.overlay,
            output_path=output_path,
            offset_frames=offset_frames,
            fps=args.fps,
            start_seconds=args.start,
            duration_seconds=args.duration,
            video_layout=args.video_layout,
            audio_mode=args.audio_mode,
            video_codec=args.video_codec,
            scale_ratio=args.scale_ratio,
            margin=args.margin,
        )
        print(f"ok: {offset_frames} -> {output_path}")


if __name__ == "__main__":
    main()
