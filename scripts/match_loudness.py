#!/usr/bin/env python

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path


def require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"Required executable '{name}' was not found on PATH.")
    return path


def extract_json_object(text: str) -> dict:
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise RuntimeError(f"Could not find loudnorm JSON in ffmpeg output:\n{text}")
    return json.loads(match.group(0))


def loudnorm_measure(
    path: Path, target_i: float, target_lra: float, target_tp: float
) -> dict:
    ffmpeg = require_tool("ffmpeg")
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-i",
        str(path),
        "-map",
        "0:a:0",
        "-af",
        f"loudnorm=I={target_i}:LRA={target_lra}:TP={target_tp}:print_format=json",
        "-f",
        "null",
        "-",
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    payload = result.stderr or result.stdout
    stats = extract_json_object(payload)
    return {
        "input": str(path.resolve()),
        "input_i": float(stats["input_i"]),
        "input_tp": float(stats["input_tp"]),
        "input_lra": float(stats["input_lra"]),
        "input_thresh": float(stats["input_thresh"]),
        "output_i": float(stats["output_i"]),
        "output_tp": float(stats["output_tp"]),
        "output_lra": float(stats["output_lra"]),
        "output_thresh": float(stats["output_thresh"]),
        "normalization_type": stats["normalization_type"],
        "target_offset": float(stats["target_offset"]),
    }


def loudnorm_filter_string(
    stats: dict, target_i: float, target_lra: float, target_tp: float
) -> str:
    return (
        f"loudnorm=I={target_i}:LRA={target_lra}:TP={target_tp}:"
        f"measured_I={stats['input_i']}:"
        f"measured_LRA={stats['input_lra']}:"
        f"measured_TP={stats['input_tp']}:"
        f"measured_thresh={stats['input_thresh']}:"
        f"offset={stats['target_offset']}:"
        "linear=true:print_format=summary"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure loudness and emit reusable second-pass loudnorm parameters."
    )
    parser.add_argument(
        "inputs", nargs="+", type=Path, help="One or more input media files."
    )
    parser.add_argument(
        "--target-i",
        type=float,
        default=-16.0,
        help="Integrated loudness target in LUFS.",
    )
    parser.add_argument(
        "--target-lra", type=float, default=11.0, help="Loudness range target."
    )
    parser.add_argument(
        "--target-tp", type=float, default=-1.5, help="True peak target in dBTP."
    )
    args = parser.parse_args()

    outputs = []
    for path in args.inputs:
        stats = loudnorm_measure(
            path,
            target_i=args.target_i,
            target_lra=args.target_lra,
            target_tp=args.target_tp,
        )
        outputs.append(
            {
                "input": stats["input"],
                "measurement": stats,
                "second_pass_filter": loudnorm_filter_string(
                    stats,
                    target_i=args.target_i,
                    target_lra=args.target_lra,
                    target_tp=args.target_tp,
                ),
            }
        )

    result = {
        "target": {
            "integrated_lufs": args.target_i,
            "lra": args.target_lra,
            "true_peak_dbtp": args.target_tp,
        },
        "tracks": outputs,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
