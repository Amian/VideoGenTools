from __future__ import annotations

import argparse
from pathlib import Path

from lib.common import run_command
from lib.pipeline import get_run_dir, load_clips_manifest, load_run_manifest, update_clip_entry


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract the first frame for a single clip.")
    parser.add_argument("--run-id", required=True, help="Run identifier.")
    parser.add_argument("--clip-id", required=True, help="Clip identifier, for example clip_0001.")
    parser.add_argument("--overwrite", action="store_true", help="Rebuild the image even if it already exists.")
    return parser.parse_args()


def extract_first_frame(run_id: str, clip_id: str, overwrite: bool = False) -> Path:
    clips_manifest = load_clips_manifest(run_id)
    clip = next((item for item in clips_manifest["clips"] if item["clip_id"] == clip_id), None)
    if clip is None:
        raise KeyError(f"Clip not found: {clip_id}")

    output_path = get_run_dir(run_id) / "frames" / f"{clip_id}.jpg"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if overwrite or not output_path.exists():
        input_path: str
        timestamp: float | None = None
        if clip.get("clip_path"):
            input_path = clip["clip_path"]
        else:
            run_manifest = load_run_manifest(run_id)
            input_path = run_manifest.get("input_video") or run_manifest.get("source_video")
            if not input_path:
                raise ValueError("Run does not have an input video.")
            timestamp = clip.get("start_time_seconds")
            if timestamp is None:
                timestamp = clip.get("start_time")
            if timestamp is None:
                raise ValueError(f"Clip {clip_id} is missing both clip_path and start timestamp.")

        command = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
        ]
        if timestamp is not None:
            command.extend(["-ss", str(timestamp)])
        command.extend(
            [
                "-i",
                input_path,
                "-frames:v",
                "1",
                "-q:v",
                "2",
                "-update",
                "1",
                str(output_path),
            ]
        )
        run_command(
            command
        )

    update_clip_entry(
        run_id,
        clip_id,
        {
            "first_frame_path": str(output_path),
            "status": "first_frame_extracted",
        },
    )
    return output_path


def main() -> None:
    args = parse_args()
    output_path = extract_first_frame(args.run_id, args.clip_id, overwrite=args.overwrite)
    print(f"First frame written: {output_path}")


if __name__ == "__main__":
    main()
