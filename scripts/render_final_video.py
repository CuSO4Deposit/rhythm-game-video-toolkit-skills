#!/usr/bin/env python

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
from pathlib import Path

from explore_alignment import align_videos
from match_loudness import loudnorm_filter_string, loudnorm_measure
from video_match_sampling import aggregate, collect_synced_screen_samples


def require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"Required executable '{name}' was not found on PATH.")
    return path


def shell_join(parts: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in parts)


def build_filter_complex(
    video_layout: str,
    scale_ratio: float,
    margin: int,
    audio_mode: str,
    base_video_filter: str | None,
    overlay_video_filter: str | None,
    base_audio_filter: str | None,
    overlay_audio_filter: str | None,
) -> str:
    base_video_chain = []
    if base_video_filter:
        base_video_chain.append(base_video_filter)
    base_video_chain.append("null")
    main_video = ""
    if video_layout == "pip_top_right_30":
        overlay_video_chain = []
        if overlay_video_filter:
            overlay_video_chain.append(overlay_video_filter)
        overlay_video_chain.append(f"scale=iw*{scale_ratio}:ih*{scale_ratio}")
        overlay_video = f"[1:v]{','.join(overlay_video_chain)}[pip]"
        main_video = f"{overlay_video};[0:v]{','.join(base_video_chain)}[basev];[basev][pip]overlay=x=W-w-{margin}:y={margin}[vout]"
    elif video_layout == "base_only":
        main_video = f"[0:v]{','.join(base_video_chain)}[vout]"
    else:
        raise ValueError(f"Unsupported video layout: {video_layout}")

    if audio_mode == "base":
        chain = base_audio_filter or "anull"
        audio = f"[0:a]{chain}[aout]"
    elif audio_mode == "overlay":
        chain = overlay_audio_filter or "anull"
        audio = f"[1:a]{chain}[aout]"
    elif audio_mode == "mix":
        base_chain = base_audio_filter or "anull"
        overlay_chain = overlay_audio_filter or "anull"
        audio = f"[0:a]{base_chain}[a0];[1:a]{overlay_chain}[a1];[a0][a1]amix=inputs=2:normalize=0[aout]"
    else:
        raise ValueError(f"Unsupported audio mode: {audio_mode}")

    return f"{main_video};{audio}"


def chain_filters(*filters: str | None) -> str | None:
    parts = [item for item in filters if item]
    if not parts:
        return None
    return ",".join(parts)


def encoder_args(video_codec: str) -> list[str]:
    if video_codec == "libx264":
        return ["-c:v", "libx264", "-preset", "medium", "-crf", "18"]
    if video_codec == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "22", "-b:v", "0"]
    raise ValueError(f"Unsupported video codec: {video_codec}")


def input_args(hwaccel: str | None) -> list[str]:
    if hwaccel is None:
        return []
    if hwaccel == "cuda":
        return ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
    raise ValueError(f"Unsupported hwaccel: {hwaccel}")


def analyze_video_match(
    base: Path,
    overlay: Path,
    trim_frames: int,
    include_clarity: bool,
    include_brightness: bool,
    include_color_balance: bool,
) -> dict[str, dict | None]:
    if not any([include_clarity, include_brightness, include_color_balance]):
        return {"clarity": None, "brightness": None, "color_balance": None}

    from match_brightness import brightness_stats, recommend_eq
    from match_clarity import clarity_stats, recommend_filter_chain
    from match_color_balance import color_stats, recommend_filter

    samples = collect_synced_screen_samples(
        base=base, overlay=overlay, trim_frames=trim_frames
    )
    result: dict[str, dict | None] = {
        "clarity": None,
        "brightness": None,
        "color_balance": None,
    }

    if include_clarity:
        base_stats = aggregate(
            [clarity_stats(frame) for frame in samples["base_frames"]]
        )
        overlay_stats = aggregate(
            [clarity_stats(frame) for frame in samples["overlay_frames"]]
        )
        result["clarity"] = {
            "base": str(base.resolve()),
            "overlay": str(overlay.resolve()),
            "trim_frames": trim_frames,
            "screen_detection": samples["screen_detection"],
            "base_screen_stats": base_stats,
            "overlay_stats": overlay_stats,
            "recommendation": recommend_filter_chain(base_stats, overlay_stats),
        }

    if include_brightness:
        base_stats = aggregate(
            [brightness_stats(frame) for frame in samples["base_frames"]]
        )
        overlay_stats = aggregate(
            [brightness_stats(frame) for frame in samples["overlay_frames"]]
        )
        result["brightness"] = {
            "base": str(base.resolve()),
            "overlay": str(overlay.resolve()),
            "trim_frames": trim_frames,
            "screen_detection": samples["screen_detection"],
            "base_screen_stats": base_stats,
            "overlay_stats": overlay_stats,
            "recommendation": recommend_eq(base_stats, overlay_stats),
        }

    if include_color_balance:
        base_stats = aggregate([color_stats(frame) for frame in samples["base_frames"]])
        overlay_stats = aggregate(
            [color_stats(frame) for frame in samples["overlay_frames"]]
        )
        result["color_balance"] = {
            "base": str(base.resolve()),
            "overlay": str(overlay.resolve()),
            "trim_frames": trim_frames,
            "screen_detection": samples["screen_detection"],
            "base_screen_stats": base_stats,
            "overlay_stats": overlay_stats,
            "recommendation": recommend_filter(base_stats, overlay_stats),
        }

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render the final aligned PiP video with optional brightness and loudness matching."
    )
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--overlay", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--trim-frames",
        type=int,
        default=None,
        help="If omitted, estimate automatically.",
    )
    parser.add_argument("--fps", type=float, default=60.0)
    parser.add_argument(
        "--video-layout",
        choices=["pip_top_right_30", "base_only"],
        default="pip_top_right_30",
        help="Visual output mode. 'pip_top_right_30' overlays the iPad video; 'base_only' keeps only the phone video.",
    )
    parser.add_argument("--scale-ratio", type=float, default=0.30)
    parser.add_argument("--margin", type=int, default=48)
    parser.add_argument(
        "--audio-mode", choices=["base", "overlay", "mix"], default="mix"
    )
    parser.add_argument("--target-i", type=float, default=-16.0)
    parser.add_argument("--target-lra", type=float, default=11.0)
    parser.add_argument("--target-tp", type=float, default=-1.5)
    parser.add_argument(
        "--overlay-brightness-match",
        action="store_true",
        help="Apply brightness matching to the overlay video. Disabled by default because the direct screen recording is treated as the reference image.",
    )
    parser.add_argument("--enhance-base-clarity", action="store_true")
    parser.add_argument("--no-base-color-match", action="store_true")
    parser.add_argument(
        "--no-base-audio-denoise",
        action="store_true",
        help="Disable the default conservative denoise step on the base audio before loudness normalization.",
    )
    parser.add_argument("--no-loudness-match", action="store_true")
    parser.add_argument(
        "--video-codec", choices=["libx264", "h264_nvenc"], default="libx264"
    )
    parser.add_argument("--hwaccel", choices=["cuda"], default=None)
    parser.add_argument("--print-command", action="store_true")
    args = parser.parse_args()

    trim_frames = args.trim_frames
    alignment = None
    if trim_frames is None:
        alignment = align_videos(
            base=args.base,
            overlay=args.overlay,
            fps=args.fps,
            max_lag_seconds=12.0,
            detect_screen=True,
        )
        trim_frames = alignment["recommended_alignment"]["overlay_minus_base_frames"]

    base_video_filter = None
    clarity = None
    color_balance = None
    base_video_filters: list[str] = []
    brightness = None
    analyses = analyze_video_match(
        base=args.base,
        overlay=args.overlay,
        trim_frames=trim_frames,
        include_clarity=args.enhance_base_clarity,
        include_brightness=(
            args.video_layout == "pip_top_right_30" and args.overlay_brightness_match
        ),
        include_color_balance=not args.no_base_color_match,
    )
    color_balance = analyses["color_balance"]
    clarity = analyses["clarity"]
    brightness = analyses["brightness"]
    if color_balance:
        base_video_filters.append(color_balance["recommendation"]["ffmpeg_filter"])
    if clarity:
        base_video_filters.append(clarity["recommendation"]["ffmpeg_filter_chain"])
    if base_video_filters:
        base_video_filter = ",".join(base_video_filters)

    overlay_video_filter = None
    if brightness:
        overlay_video_filter = brightness["recommendation"]["ffmpeg_eq"]

    base_audio_filter = None
    overlay_audio_filter = None
    loudness = None
    if not args.no_loudness_match:
        base_stats = loudnorm_measure(
            args.base, args.target_i, args.target_lra, args.target_tp
        )
        overlay_stats = loudnorm_measure(
            args.overlay, args.target_i, args.target_lra, args.target_tp
        )
        base_audio_filter = loudnorm_filter_string(
            base_stats, args.target_i, args.target_lra, args.target_tp
        )
        overlay_audio_filter = loudnorm_filter_string(
            overlay_stats, args.target_i, args.target_lra, args.target_tp
        )
        if args.audio_mode in {"base", "mix"} and not args.no_base_audio_denoise:
            base_audio_filter = chain_filters(
                "afftdn=nf=-28:om=o",
                base_audio_filter,
            )
        loudness = {
            "base": base_stats,
            "overlay": overlay_stats,
        }

    filter_complex = build_filter_complex(
        video_layout=args.video_layout,
        scale_ratio=args.scale_ratio,
        margin=args.margin,
        audio_mode=args.audio_mode,
        base_video_filter=base_video_filter,
        overlay_video_filter=overlay_video_filter,
        base_audio_filter=base_audio_filter,
        overlay_audio_filter=overlay_audio_filter,
    )

    ffmpeg_bin = "ffmpeg" if args.print_command else require_tool("ffmpeg")
    trim_seconds = trim_frames / args.fps
    cmd = [
        ffmpeg_bin,
        "-y",
        *input_args(args.hwaccel),
        "-i",
        str(args.base),
        "-ss",
        f"{trim_seconds:.6f}",
        *input_args(args.hwaccel),
        "-i",
        str(args.overlay),
        "-filter_complex",
        filter_complex,
        "-map",
        "[vout]",
        "-map",
        "[aout]",
        *encoder_args(args.video_codec),
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-shortest",
        str(args.output),
    ]

    payload = {
        "trim_frames": trim_frames,
        "trim_seconds": trim_seconds,
        "alignment": alignment,
        "clarity": clarity,
        "color_balance": color_balance,
        "brightness": brightness,
        "loudness": loudness,
        "video_layout": args.video_layout,
        "video_codec": args.video_codec,
        "hwaccel": args.hwaccel,
        "filter_complex": filter_complex,
        "command": shell_join(cmd),
    }

    if args.print_command:
        print(json.dumps(payload, indent=2))
        return

    subprocess.run(cmd, check=True)
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
