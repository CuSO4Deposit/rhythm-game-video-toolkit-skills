#!/usr/bin/env python

from __future__ import annotations

import argparse
import shlex
import shutil
import subprocess
from pathlib import Path

from pip_layout import resolve_scale_ratio


def require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"Required executable '{name}' was not found on PATH.")
    return path


def shell_join(parts: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in parts)


def build_filter_complex(scale_ratio: float, margin: int, audio_mode: str) -> str:
    scale_expr = f"scale=iw*{scale_ratio}:ih*{scale_ratio}"
    video = f"[1:v]{scale_expr}[pip];[0:v][pip]overlay=x=W-w-{margin}:y={margin}[vout]"
    if audio_mode == "base":
        audio = "[0:a]anull[aout]"
    elif audio_mode == "overlay":
        audio = "[1:a]anull[aout]"
    elif audio_mode == "mix":
        audio = "[0:a][1:a]amix=inputs=2:normalize=0[aout]"
    else:
        raise ValueError(f"Unsupported audio mode: {audio_mode}")
    return f"{video};{audio}"


def build_command(
    base: Path,
    overlay: Path,
    output: Path,
    trim_frames: int,
    fps: float,
    scale_ratio: float,
    margin: int,
    audio_mode: str,
    extra_video_filters: str | None = None,
    ffmpeg_bin: str = "ffmpeg",
) -> list[str]:
    trim_seconds = trim_frames / fps
    filter_complex = build_filter_complex(
        scale_ratio=scale_ratio, margin=margin, audio_mode=audio_mode
    )
    if extra_video_filters:
        filter_complex = filter_complex.replace(
            "[vout]", f",{extra_video_filters}[vout]"
        )
    cmd = [
        ffmpeg_bin,
        "-y",
        "-i",
        str(base),
        "-ss",
        f"{trim_seconds:.6f}",
        "-i",
        str(overlay),
        "-filter_complex",
        filter_complex,
        "-map",
        "[vout]",
        "-map",
        "[aout]",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        str(output),
    ]
    return cmd


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compose a picture-in-picture video after the overlay has been aligned to the base."
    )
    parser.add_argument(
        "--base",
        type=Path,
        required=True,
        help="Main video, usually the phone recording.",
    )
    parser.add_argument(
        "--overlay",
        type=Path,
        required=True,
        help="Overlay video, usually the iPad recording.",
    )
    parser.add_argument("--output", type=Path, required=True, help="Output video path.")
    parser.add_argument(
        "--trim-frames",
        type=int,
        required=True,
        help="Trim this many frames from the overlay head.",
    )
    parser.add_argument("--fps", type=float, default=60.0)
    parser.add_argument(
        "--pip-scale-percent",
        type=float,
        default=25.0,
        help="PiP overlay width/height scaling percent. Default: 25.",
    )
    parser.add_argument(
        "--scale-ratio",
        type=float,
        default=None,
        help="Legacy PiP scale ratio override. If set, it takes precedence over --pip-scale-percent.",
    )
    parser.add_argument(
        "--margin", type=int, default=48, help="Top-right margin in output pixels."
    )
    parser.add_argument(
        "--audio-mode",
        choices=["base", "overlay", "mix"],
        default="mix",
        help="Which audio to keep in the output.",
    )
    parser.add_argument(
        "--extra-video-filters",
        type=str,
        default=None,
        help="Extra ffmpeg video filters to append to the composed output before encoding.",
    )
    parser.add_argument(
        "--print-command",
        action="store_true",
        help="Print the ffmpeg command instead of running it.",
    )
    args = parser.parse_args()

    ffmpeg_bin = "ffmpeg" if args.print_command else require_tool("ffmpeg")
    cmd = build_command(
        base=args.base,
        overlay=args.overlay,
        output=args.output,
        trim_frames=args.trim_frames,
        fps=args.fps,
        scale_ratio=resolve_scale_ratio(args.scale_ratio, args.pip_scale_percent),
        margin=args.margin,
        audio_mode=args.audio_mode,
        extra_video_filters=args.extra_video_filters,
        ffmpeg_bin=ffmpeg_bin,
    )

    if args.print_command:
        print(shell_join(cmd))
        return

    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()
