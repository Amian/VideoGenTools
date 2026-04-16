from __future__ import annotations

import argparse

from analyze_clip import analyze_clip
from lib.pipeline import load_clips_manifest, load_run_manifest, save_run_manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze all split clips.")
    parser.add_argument("--run-id", required=True, help="Run identifier.")
    parser.add_argument("--overwrite", action="store_true", help="Rebuild analysis files even if they already exist.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    clips_manifest = load_clips_manifest(args.run_id)
    clips = clips_manifest.get("clips", [])
    if not clips:
        raise ValueError("No clips found. Run detect_scenes.py and split_clips.py first.")

    for clip in clips:
        analyze_clip(args.run_id, clip["clip_id"], overwrite=args.overwrite)

    run_manifest = load_run_manifest(args.run_id)
    run_manifest["status"] = "clips_analyzed"
    run_manifest.setdefault("steps", {})
    run_manifest["steps"]["analyze_all_clips"] = {
        "status": "completed",
        "updated_at": None,
    }
    save_run_manifest(args.run_id, run_manifest)
    run_manifest = load_run_manifest(args.run_id)
    run_manifest["steps"]["analyze_all_clips"]["updated_at"] = run_manifest["updated_at"]
    save_run_manifest(args.run_id, run_manifest)

    print(f"Run ID: {args.run_id}")
    print(f"Analyzed clips: {len(clips)}")


if __name__ == "__main__":
    main()
