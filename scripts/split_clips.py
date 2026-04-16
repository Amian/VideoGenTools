from __future__ import annotations

import argparse
from pathlib import Path

from lib.common import run_command
from lib.pipeline import create_run_directories, get_clip_dir, load_clips_manifest, load_run_manifest, save_clips_manifest, save_run_manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Split the ingested video into per-scene clips.")
    parser.add_argument("--run-id", required=True, help="Run identifier.")
    parser.add_argument("--overwrite", action="store_true", help="Rebuild clip files even if they already exist.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    create_run_directories(args.run_id)
    run_manifest = load_run_manifest(args.run_id)
    clips_manifest = load_clips_manifest(args.run_id)
    input_video = run_manifest.get("input_video")
    if not input_video:
        raise ValueError("Run does not have an ingested input video yet.")

    input_path = Path(input_video)
    clips = clips_manifest.get("clips", [])
    if not clips:
        raise ValueError("No clips found. Run detect_scenes.py first.")

    for clip in clips:
        clip_dir = get_clip_dir(args.run_id, clip["clip_id"])
        clip_dir.mkdir(parents=True, exist_ok=True)
        output_path = clip_dir / "clip.mp4"

        if args.overwrite or not output_path.exists():
            duration = max(float(clip["duration_seconds"]), 0.1)
            run_command(
                [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    str(input_path),
                    "-ss",
                    str(clip["start_time"]),
                    "-t",
                    str(duration),
                    "-map",
                    "0:v:0",
                    "-map",
                    "0:a?",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "18",
                    "-c:a",
                    "aac",
                    "-movflags",
                    "+faststart",
                    str(output_path),
                ]
            )

        clip["clip_path"] = str(output_path)
        clip["status"] = "split"

    save_clips_manifest(args.run_id, clips_manifest)
    run_manifest["status"] = "clips_split"
    run_manifest.setdefault("steps", {})
    run_manifest["steps"]["split_clips"] = {
        "status": "completed",
        "updated_at": None,
    }
    save_run_manifest(args.run_id, run_manifest)
    run_manifest = load_run_manifest(args.run_id)
    run_manifest["steps"]["split_clips"]["updated_at"] = run_manifest["updated_at"]
    save_run_manifest(args.run_id, run_manifest)

    print(f"Run ID: {args.run_id}")
    print(f"Split clips written: {len(clips)}")


if __name__ == "__main__":
    main()
