from __future__ import annotations

import statistics
import re
import subprocess
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


def sample_center_frame_change_scores(
    video_path: Path,
    *,
    fps: int = 8,
    width: int = 48,
    height: int = 48,
    crop_margin: int = 10,
) -> list[tuple[float, float]]:
    frame_size = width * height * 3
    process = subprocess.Popen(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video_path),
            "-vf",
            f"fps={fps},scale={width}:{height},format=rgb24",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    if process.stdout is None:
        raise RuntimeError("Could not open ffmpeg stdout for frame sampling.")

    scores: list[tuple[float, float]] = []
    previous_frame: bytes | None = None
    frame_index = 0

    while True:
        buffer = process.stdout.read(frame_size)
        if len(buffer) < frame_size:
            break

        if previous_frame is not None:
            total = 0.0
            count = 0
            for y in range(height):
                row_offset = y * width * 3
                for x in range(width):
                    if not (crop_margin <= x < width - crop_margin and crop_margin <= y < height - crop_margin):
                        continue
                    offset = row_offset + x * 3
                    difference = (
                        abs(buffer[offset] - previous_frame[offset])
                        + abs(buffer[offset + 1] - previous_frame[offset + 1])
                        + abs(buffer[offset + 2] - previous_frame[offset + 2])
                    ) / 3.0
                    total += difference
                    count += 1
            if count:
                scores.append((frame_index / fps, total / count))

        previous_frame = buffer
        frame_index += 1

    process.wait()
    if process.returncode != 0:
        stderr_text = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
        raise RuntimeError(f"ffmpeg frame sampling failed.\n{stderr_text.strip()}")

    return scores


def average_motion_for_segment(
    scores: list[tuple[float, float]],
    start_time: float,
    end_time: float,
) -> float:
    values = [score for timestamp, score in scores if start_time < timestamp <= end_time]
    if not values:
        return 0.0
    return float(statistics.mean(values))


def prune_trailing_low_motion_clip(
    boundaries: list[float],
    duration: float,
    scores: list[tuple[float, float]],
    *,
    min_trailing_duration: float = 2.5,
    duration_multiplier: float = 2.5,
    low_motion_ratio: float = 0.6,
    absolute_motion_threshold: float = 5.0,
) -> list[float]:
    if len(boundaries) < 2:
        return boundaries

    clip_starts = list(boundaries)
    clip_ends = clip_starts[1:] + [duration]
    clip_durations = [max(0.0, end - start) for start, end in zip(clip_starts, clip_ends)]
    last_duration = clip_durations[-1]
    if last_duration < min_trailing_duration:
        return boundaries

    previous_durations = clip_durations[:-1]
    if not previous_durations:
        return boundaries

    median_previous_duration = statistics.median(previous_durations)
    if last_duration < median_previous_duration * duration_multiplier:
        return boundaries

    clip_motion = [average_motion_for_segment(scores, start, end) for start, end in zip(clip_starts, clip_ends)]
    last_motion = clip_motion[-1]
    previous_motion = clip_motion[:-1]
    if not previous_motion:
        return boundaries

    median_previous_motion = statistics.median(previous_motion)
    motion_limit = max(absolute_motion_threshold, median_previous_motion * low_motion_ratio)
    if last_motion > motion_limit:
        return boundaries

    return boundaries[:-1]
