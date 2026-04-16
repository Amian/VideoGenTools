from __future__ import annotations

import re
from pathlib import Path

from .common import get_video_metadata, run_command


PTS_TIME_PATTERN = re.compile(r"pts_time:(\d+(?:\.\d+)?)")


def detect_scene_boundaries(
    video_path: Path,
    *,
    threshold: float = 0.35,
    min_scene_length: float = 1.0,
) -> tuple[list[float], float]:
    metadata = get_video_metadata(video_path)
    duration = float(metadata.get("duration_seconds") or 0.0)
    if duration <= 0:
        raise ValueError(f"Could not determine duration for {video_path}")

    filter_expression = f"select='gt(scene,{threshold})',showinfo"
    result = run_command(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(video_path),
            "-filter:v",
            filter_expression,
            "-an",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
    )

    timestamps: list[float] = []
    for line in result.stderr.splitlines():
        match = PTS_TIME_PATTERN.search(line)
        if not match:
            continue
        timestamp = float(match.group(1))
        if timestamp <= 0:
            continue
        if timestamps and timestamp - timestamps[-1] < min_scene_length:
            continue
        if duration - timestamp < 0.05:
            continue
        timestamps.append(timestamp)

    boundaries = [0.0]
    boundaries.extend(timestamps)
    return boundaries, duration

