#!/usr/bin/env python

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path


INPUT_EXTENSIONS = {".mp4", ".MP4", ".mov", ".MOV", ".mkv", ".MKV"}


def require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"Required executable '{name}' was not found on PATH.")
    return path


def remove_last_suffix(path: Path) -> str:
    parts = path.name.split(".")
    if len(parts) <= 1:
        return path.name
    return ".".join(parts[:-1])


def build_attempts(
    ffmpeg_bin: str,
    input_path: Path,
    output_path: Path,
    fps: int,
) -> list[tuple[str, list[str]]]:
    common_prefix = [
        ffmpeg_bin,
        "-y",
        "-i",
        str(input_path),
        "-r",
        str(fps),
    ]
    common_suffix = [
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    return [
        (
            "cuda_decode_nvenc",
            [
                ffmpeg_bin,
                "-y",
                "-hwaccel",
                "cuda",
                "-hwaccel_output_format",
                "cuda",
                "-i",
                str(input_path),
                "-r",
                str(fps),
                "-c:v",
                "h264_nvenc",
                "-preset",
                "fast",
                "-c:a",
                "aac",
                "-b:a",
                "160k",
                "-movflags",
                "+faststart",
                str(output_path),
            ],
        ),
        (
            "cpu_decode_nvenc",
            common_prefix + ["-c:v", "h264_nvenc", "-preset", "fast"] + common_suffix,
        ),
        (
            "cpu_decode_x264",
            common_prefix
            + ["-c:v", "libx264", "-preset", "medium", "-crf", "20"]
            + common_suffix,
        ),
    ]


def compress_file(
    ffmpeg_bin: str, input_path: Path, output_path: Path, fps: int
) -> dict:
    attempts_log: list[dict[str, str | int]] = []
    for name, command in build_attempts(ffmpeg_bin, input_path, output_path, fps):
        result = subprocess.run(command, capture_output=True, text=True)
        attempts_log.append(
            {
                "attempt": name,
                "returncode": result.returncode,
                "stderr_tail": "\n".join(result.stderr.splitlines()[-20:]),
            }
        )
        if result.returncode == 0:
            return {
                "input": str(input_path),
                "output": str(output_path),
                "status": "ok",
                "strategy": name,
                "attempts": attempts_log,
            }
        if output_path.exists():
            output_path.unlink()
    return {
        "input": str(input_path),
        "output": str(output_path),
        "status": "failed",
        "strategy": None,
        "attempts": attempts_log,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Normalize raw video files into 60 fps MP4 staging files with CUDA/NVENC fallbacks."
    )
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--fps", type=int, choices=[30, 60], default=60)
    parser.add_argument("--print-json", action="store_true")
    args = parser.parse_args()

    ffmpeg_bin = require_tool("ffmpeg")
    input_dir = args.input_dir
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(
        path
        for path in input_dir.iterdir()
        if path.is_file() and path.suffix in INPUT_EXTENSIONS
    )
    existing = {
        remove_last_suffix(path) for path in output_dir.iterdir() if path.is_file()
    }

    results = []
    for input_path in files:
        base_name = remove_last_suffix(input_path)
        output_path = output_dir / f"{base_name}.mp4"
        if base_name in existing and output_path.exists():
            results.append(
                {
                    "input": str(input_path),
                    "output": str(output_path),
                    "status": "skipped_existing",
                    "strategy": None,
                }
            )
            continue
        results.append(compress_file(ffmpeg_bin, input_path, output_path, args.fps))

    payload = {
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "results": results,
    }
    if args.print_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    for item in results:
        print(f"{item['status']}: {item['input']} -> {item['output']}")


if __name__ == "__main__":
    main()
