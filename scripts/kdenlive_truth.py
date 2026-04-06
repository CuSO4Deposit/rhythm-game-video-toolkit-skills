#!/usr/bin/env python

from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from pathlib import Path


def timecode_to_seconds(value: str) -> float:
    hours, minutes, seconds = value.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


@dataclass
class ClipPlacement:
    producer_id: str
    resource: str
    source_in_seconds: float
    source_out_seconds: float
    source_in_frames: int
    source_out_frames: int
    timeline_start_seconds: float
    timeline_start_frames: int
    timeline_duration_frames: int


def parse_project_profile(root: ET.Element) -> tuple[float, str]:
    main_bin = root.find("./playlist[@id='main_bin']")
    if main_bin is None:
        raise ValueError("Could not find main_bin playlist in project.")
    profile_name = ""
    for prop in main_bin.findall("property"):
        if prop.attrib.get("name") == "kdenlive:docproperties.profile":
            profile_name = (prop.text or "").strip()
            break
    if not profile_name:
        raise ValueError("Could not find kdenlive profile in project.")
    if profile_name == "atsc_1080p_60":
        return 60.0, profile_name
    if profile_name.endswith("_60"):
        return 60.0, profile_name
    raise ValueError(f"Unsupported profile for now: {profile_name}")


def collect_resources(root: ET.Element, project_root: Path) -> dict[str, Path]:
    resources: dict[str, Path] = {}
    for producer_tag in ("chain", "producer"):
        for node in root.findall(producer_tag):
            resource = None
            for prop in node.findall("property"):
                if prop.attrib.get("name") == "resource":
                    resource = (prop.text or "").strip()
                    break
            if resource and not resource.startswith("black"):
                resources[node.attrib["id"]] = (project_root / resource).resolve()
    return resources


def infer_timeline_placements(
    root: ET.Element, fps: float, project_root: Path
) -> list[ClipPlacement]:
    resources = collect_resources(root, project_root)
    placements: list[ClipPlacement] = []
    for playlist in root.findall("playlist"):
        if playlist.attrib.get("id") == "main_bin":
            continue
        timeline_cursor_frames = 0
        entry = None
        for child in list(playlist):
            if child.tag == "blank":
                timeline_cursor_frames += round(
                    timecode_to_seconds(child.attrib["length"]) * fps
                )
            elif child.tag == "entry":
                entry = child
                break
        if entry is None:
            continue
        producer_id = entry.attrib.get("producer", "")
        if producer_id not in resources:
            continue
        source_in = timecode_to_seconds(entry.attrib["in"])
        source_out = timecode_to_seconds(entry.attrib["out"])
        source_in_frames = round(source_in * fps)
        source_out_frames = round(source_out * fps)
        timeline_start_frames = timeline_cursor_frames
        placements.append(
            ClipPlacement(
                producer_id=producer_id,
                resource=str(resources[producer_id]),
                source_in_seconds=source_in,
                source_out_seconds=source_out,
                source_in_frames=source_in_frames,
                source_out_frames=source_out_frames,
                timeline_start_seconds=timeline_start_frames / fps,
                timeline_start_frames=timeline_start_frames,
                timeline_duration_frames=source_out_frames - source_in_frames + 1,
            )
        )
    return placements


def summarize_truth(project_path: Path) -> dict:
    root = ET.parse(project_path).getroot()
    project_root = Path(root.attrib["root"])
    fps, profile_name = parse_project_profile(root)
    placements = infer_timeline_placements(root, fps, project_root)
    unique_by_resource: dict[str, ClipPlacement] = {}
    for placement in placements:
        unique_by_resource.setdefault(placement.resource, placement)
    if len(unique_by_resource) != 2:
        raise ValueError(
            f"Expected exactly 2 unique media resources, found {len(unique_by_resource)}."
        )
    clips = sorted(unique_by_resource.values(), key=lambda item: item.source_in_frames)
    reference = clips[0]
    delayed = clips[1]
    return {
        "project_path": str(project_path.resolve()),
        "project_root": str(project_root),
        "profile_name": profile_name,
        "fps": fps,
        "clips": [asdict(item) for item in clips],
        "alignment_truth": {
            "reference_video": reference.resource,
            "delayed_video": delayed.resource,
            "timeline_offset_frames": delayed.timeline_start_frames
            - reference.timeline_start_frames,
            "timeline_offset_seconds": (
                delayed.timeline_start_frames - reference.timeline_start_frames
            )
            / fps,
            "source_trim_delta_frames": delayed.source_in_frames
            - reference.source_in_frames,
            "source_trim_delta_seconds": (
                delayed.source_in_frames - reference.source_in_frames
            )
            / fps,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract alignment truth from a Kdenlive project."
    )
    parser.add_argument("project", type=Path)
    args = parser.parse_args()
    summary = summarize_truth(args.project)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
