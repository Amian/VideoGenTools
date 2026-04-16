from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from lib.pipeline import (
    create_run_directories,
    get_clips_manifest_path,
    get_run_dir,
    get_run_manifest_path,
    initialize_clips_manifest,
    initialize_run_manifest,
    save_run_manifest,
)


def setup_run(source_video: str, run_id: str | None = None, run_name: str | None = None) -> str:
    source_video_path = Path(source_video).expanduser().resolve()
    if not source_video_path.is_file():
        raise FileNotFoundError(f"Source video not found: {source_video_path}")

    resolved_run_id = run_id or f"run_{datetime.now():%Y%m%d_%H%M%S}"
    run_dir = get_run_dir(resolved_run_id)
    if run_dir.exists() and any(run_dir.iterdir()):
        raise FileExistsError(f"Run directory already exists and is not empty: {run_dir}")

    create_run_directories(resolved_run_id)

    run_manifest = initialize_run_manifest(resolved_run_id, str(source_video_path), run_name)
    save_run_manifest(resolved_run_id, run_manifest)
    initialize_clips_manifest(resolved_run_id)
    return resolved_run_id


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a new processing run.")
    parser.add_argument("--source-video", required=True, help="Path to the source video.")
    parser.add_argument("--run-id", help="Optional explicit run identifier.")
    parser.add_argument("--run-name", help="Optional display name for the run.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_id = setup_run(args.source_video, run_id=args.run_id, run_name=args.run_name)
    run_dir = get_run_dir(run_id)
    source_video = Path(args.source_video).expanduser().resolve()
    if not source_video.is_file():
        raise FileNotFoundError(f"Source video not found: {source_video}")

    print(f"Created run: {run_id}")
    print(f"Run directory: {run_dir}")
    print(f"Run manifest: {get_run_manifest_path(run_id)}")
    print(f"Clips manifest: {get_clips_manifest_path(run_id)}")


if __name__ == "__main__":
    main()
