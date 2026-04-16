from __future__ import annotations

import argparse

from extract_first_frame import extract_first_frame
from lib.pipeline import load_clips_manifest, load_run_manifest, save_run_manifest


def extract_all_first_frames(run_id: str, overwrite: bool = False) -> int:
    clips_manifest = load_clips_manifest(run_id)
    clips = clips_manifest.get("clips", [])
    if not clips:
        raise ValueError("No clips found. Generate a clips manifest first.")

    for clip in clips:
        extract_first_frame(run_id, clip["clip_id"], overwrite=overwrite)

    run_manifest = load_run_manifest(run_id)
    run_manifest["status"] = "first_frames_extracted"
    run_manifest.setdefault("steps", {})
    run_manifest["steps"]["extract_all_first_frames"] = {
        "status": "completed",
        "updated_at": None,
    }
    save_run_manifest(run_id, run_manifest)
    run_manifest = load_run_manifest(run_id)
    run_manifest["steps"]["extract_all_first_frames"]["updated_at"] = run_manifest["updated_at"]
    save_run_manifest(run_id, run_manifest)
    return len(clips)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract the first frame for every clip in a run.")
    parser.add_argument("--run-id", required=True, help="Run identifier.")
    parser.add_argument("--overwrite", action="store_true", help="Rebuild images even if they already exist.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    clip_count = extract_all_first_frames(args.run_id, overwrite=args.overwrite)

    print(f"Run ID: {args.run_id}")
    print(f"Extracted first frames: {clip_count}")


if __name__ == "__main__":
    main()
