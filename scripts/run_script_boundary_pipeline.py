from __future__ import annotations

import argparse

from detect_scenes import detect_scenes
from export_clip_boundaries import export_clip_boundaries
from extract_all_first_frames import extract_all_first_frames
from ingest_video import ingest_video
from lib.pipeline import get_run_dir
from setup_run import setup_run


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the local script-based boundary pipeline from source video to clip-start images and timing JSON."
    )
    parser.add_argument("--source-video", required=True, help="Path to the source video.")
    parser.add_argument("--run-id", help="Optional explicit run identifier.")
    parser.add_argument("--run-name", help="Optional display name for the run.")
    parser.add_argument("--threshold", type=float, default=0.35, help="FFmpeg scene detection threshold.")
    parser.add_argument(
        "--min-scene-length",
        type=float,
        default=1.0,
        help="Minimum number of seconds between detected clip starts.",
    )
    parser.add_argument(
        "--symlink-input",
        action="store_true",
        help="Symlink the source video into the run folder instead of copying it.",
    )
    parser.add_argument("--overwrite-frames", action="store_true", help="Rebuild first-frame images if they exist.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    run_id = setup_run(args.source_video, run_id=args.run_id, run_name=args.run_name)
    ingest_video(run_id, mode="symlink" if args.symlink_input else "copy")
    clip_count = detect_scenes(run_id, threshold=args.threshold, min_scene_length=args.min_scene_length)
    frame_count = extract_all_first_frames(run_id, overwrite=args.overwrite_frames)
    json_path = export_clip_boundaries(run_id)

    print(f"Run ID: {run_id}")
    print(f"Detected clips: {clip_count}")
    print(f"Extracted first frames: {frame_count}")
    print(f"Frames directory: {get_run_dir(run_id) / 'frames'}")
    print(f"Boundary JSON: {json_path}")


if __name__ == "__main__":
    main()
