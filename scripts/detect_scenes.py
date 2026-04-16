from __future__ import annotations

import argparse
from pathlib import Path

from lib.pipeline import load_clips_manifest, load_run_manifest, save_clips_manifest, save_run_manifest
from lib.scene_detection import detect_scene_boundaries, prune_trailing_low_motion_clip, sample_center_frame_change_scores


def detect_scenes(run_id: str, threshold: float = 0.35, min_scene_length: float = 0.75) -> int:
    run_manifest = load_run_manifest(run_id)
    input_video = run_manifest.get("input_video")
    if not input_video:
        raise ValueError("Run does not have an ingested input video yet.")

    boundaries, duration = detect_scene_boundaries(
        video_path=Path(input_video),
        threshold=threshold,
        min_scene_length=min_scene_length,
    )
    motion_scores = sample_center_frame_change_scores(Path(input_video))
    pruned_boundaries = prune_trailing_low_motion_clip(boundaries, duration, motion_scores)
    trailing_clip_pruned = len(pruned_boundaries) < len(boundaries)
    boundaries = pruned_boundaries

    clips = []
    for index, start_time in enumerate(boundaries, start=1):
        end_time = boundaries[index] if index < len(boundaries) else duration
        clip_duration = max(0.0, round(end_time - start_time, 3))
        if clip_duration <= 0:
            continue
        clip_id = f"clip_{index:04d}"
        clips.append(
            {
                "clip_id": clip_id,
                "index": index,
                "clip_number": index,
                "start_time": round(start_time, 3),
                "start_time_seconds": round(start_time, 3),
                "end_time": round(end_time, 3),
                "end_time_seconds": round(end_time, 3),
                "duration_seconds": clip_duration,
                "clip_path": None,
                "analysis_path": None,
                "first_frame_path": None,
                "status": "scene_detected",
            }
        )

    existing_manifest = load_clips_manifest(run_id)
    clips_manifest = {
        "run_id": run_id,
        "created_at": existing_manifest.get("created_at"),
        "scene_detection": {
            "threshold": threshold,
            "min_scene_length": min_scene_length,
            "video_duration_seconds": round(duration, 3),
            "trailing_low_motion_clip_pruned": trailing_clip_pruned,
        },
        "clips": clips,
    }
    save_clips_manifest(run_id, clips_manifest)

    run_manifest["status"] = "scenes_detected"
    run_manifest["clip_count"] = len(clips)
    run_manifest.setdefault("steps", {})
    run_manifest["steps"]["detect_scenes"] = {
        "status": "completed",
        "updated_at": None,
    }
    save_run_manifest(run_id, run_manifest)
    run_manifest = load_run_manifest(run_id)
    run_manifest["steps"]["detect_scenes"]["updated_at"] = run_manifest["updated_at"]
    save_run_manifest(run_id, run_manifest)
    return len(clips)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Detect scene boundaries in the ingested video.")
    parser.add_argument("--run-id", required=True, help="Run identifier.")
    parser.add_argument("--threshold", type=float, default=0.35, help="FFmpeg scene detection threshold.")
    parser.add_argument(
        "--min-scene-length",
        type=float,
        default=0.75,
        help="Minimum number of seconds between scene cuts.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    clip_count = detect_scenes(args.run_id, threshold=args.threshold, min_scene_length=args.min_scene_length)

    print(f"Run ID: {args.run_id}")
    print(f"Detected clips: {clip_count}")


if __name__ == "__main__":
    main()
