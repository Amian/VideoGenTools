from __future__ import annotations

import argparse
from pathlib import Path

from lib.analysis import write_clip_analysis
from lib.pipeline import get_clip_dir, load_clips_manifest, update_clip_entry


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze a single clip and write analysis.json.")
    parser.add_argument("--run-id", required=True, help="Run identifier.")
    parser.add_argument("--clip-id", required=True, help="Clip identifier, for example clip_0001.")
    parser.add_argument("--overwrite", action="store_true", help="Rebuild analysis even if it already exists.")
    return parser.parse_args()


def analyze_clip(run_id: str, clip_id: str, overwrite: bool = False) -> Path:
    clips_manifest = load_clips_manifest(run_id)
    clip = next((item for item in clips_manifest["clips"] if item["clip_id"] == clip_id), None)
    if clip is None:
        raise KeyError(f"Clip not found: {clip_id}")
    if not clip.get("clip_path"):
        raise ValueError(f"Clip {clip_id} has not been split yet.")

    clip_dir = get_clip_dir(run_id, clip_id)
    clip_dir.mkdir(parents=True, exist_ok=True)
    output_path = clip_dir / "analysis.json"
    if overwrite or not output_path.exists():
        write_clip_analysis(Path(clip["clip_path"]), output_path, clip_id)

    update_clip_entry(
        run_id,
        clip_id,
        {
            "analysis_path": str(output_path),
            "status": "analyzed",
        },
    )
    return output_path


def main() -> None:
    args = parse_args()
    output_path = analyze_clip(args.run_id, args.clip_id, overwrite=args.overwrite)
    print(f"Analysis written: {output_path}")


if __name__ == "__main__":
    main()
