from __future__ import annotations

import argparse
from pathlib import Path

from lib.common import save_json
from lib.pipeline import get_run_dir, load_clips_manifest


def export_clip_boundaries(run_id: str) -> Path:
    clips_manifest = load_clips_manifest(run_id)
    clips = clips_manifest.get("clips", [])
    if not clips:
        raise ValueError("No clips found. Run detect_scenes.py first.")

    output_payload = {
        "run_id": run_id,
        "total_clips": len(clips),
        "clips": [],
    }

    for clip in clips:
        output_payload["clips"].append(
            {
                "clip_number": clip.get("clip_number") or clip["index"],
                "start_time_seconds": round(float(clip.get("start_time_seconds", clip["start_time"])), 3),
                "duration_seconds": round(float(clip["duration_seconds"]), 3),
                "end_time_seconds": round(float(clip.get("end_time_seconds", clip["end_time"])), 3),
                "start_frame_image": clip.get("first_frame_path"),
            }
        )

    output_path = get_run_dir(run_id) / "output" / "clip-boundaries.json"
    save_json(output_path, output_payload)
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export a compact clip boundary JSON file.")
    parser.add_argument("--run-id", required=True, help="Run identifier.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = export_clip_boundaries(args.run_id)
    print(f"Run ID: {args.run_id}")
    print(f"Boundary JSON: {output_path}")


if __name__ == "__main__":
    main()
