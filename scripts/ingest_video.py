from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from lib.common import get_video_metadata
from lib.pipeline import get_run_dir, load_run_manifest, save_run_manifest


def ingest_video(run_id: str, source_video: str | None = None, mode: str = "copy") -> Path:
    run_manifest = load_run_manifest(run_id)

    source_path = Path(source_video or run_manifest["source_video"]).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"Source video not found: {source_path}")

    destination = get_run_dir(run_id) / "input" / f"source{source_path.suffix.lower()}"
    if destination.exists():
        if destination.is_symlink() or destination.is_file():
            destination.unlink()

    if mode == "copy":
        shutil.copy2(source_path, destination)
    else:
        destination.symlink_to(source_path)

    run_manifest["source_video"] = str(source_path)
    run_manifest["input_video"] = str(destination)
    run_manifest["input_metadata"] = get_video_metadata(destination)
    run_manifest["status"] = "video_ingested"
    run_manifest.setdefault("steps", {})
    run_manifest["steps"]["ingest_video"] = {
        "status": "completed",
        "updated_at": None,
    }
    save_run_manifest(run_id, run_manifest)
    run_manifest = load_run_manifest(run_id)
    run_manifest["steps"]["ingest_video"]["updated_at"] = run_manifest["updated_at"]
    save_run_manifest(run_id, run_manifest)
    return destination


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Copy or link the input video into a run directory.")
    parser.add_argument("--run-id", required=True, help="Run identifier created by setup_run.py.")
    parser.add_argument("--source-video", help="Optional override for the source video path.")
    parser.add_argument(
        "--mode",
        choices=("copy", "symlink"),
        default="copy",
        help="How to place the source video into the run directory.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    destination = ingest_video(args.run_id, source_video=args.source_video, mode=args.mode)

    print(f"Run ID: {args.run_id}")
    print(f"Ingested video: {destination}")


if __name__ == "__main__":
    main()
