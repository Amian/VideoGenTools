#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path

from chatgpt_free_image import generate_image
from lib.common import ensure_dir, save_json, timestamp_utc
from lib.pipeline import get_run_dir, load_clips_manifest, load_run_manifest, save_clips_manifest, save_run_manifest


DEFAULT_REPLACEMENT_IMAGE_PROMPT = (
    "Generate a new image based on the provided reference. "
    "The size/aspect raito of new image should be same as reference image. "
    "Keep the core context and subject consistent, including the primary elements "
    "(such as people, animals, or objects) and their actions. However, introduce subtle originality. "
    "Change minor details like the arrangement of furniture, slightly different colors, "
    "or alternative but similar scenery. The atmosphere, setting type, and overall theme "
    "should remain recognizable and coherent, but with fresh visual elements, not an exact copy. "
    "Ensure the composition and focal point remain aligned with the original purpose, "
    "but allow for slight creative variation like a different couch style, a slightly altered landscape, "
    "or a new set of background objects, without changing the fundamental context or story."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate replacement images for each clip using the saved first frame as the reference image."
    )
    parser.add_argument("--run-id", required=True, help="Existing run identifier.")
    parser.add_argument(
        "--prompt",
        default=DEFAULT_REPLACEMENT_IMAGE_PROMPT,
        help="Shared image-generation prompt to use for every clip.",
    )
    parser.add_argument("--profile", help="Optional Camoufox profile directory.")
    parser.add_argument("--url", default="https://chatgpt.com/", help="ChatGPT URL.")
    parser.add_argument("--timeout-ms", type=int, default=180000, help="Per-image generation timeout in milliseconds.")
    parser.add_argument("--max-retries", type=int, default=3, help="Maximum attempts per clip.")
    parser.add_argument("--headless", action="store_true", help="Run Camoufox headless.")
    parser.add_argument("--overwrite", action="store_true", help="Regenerate images even if they already exist.")
    return parser.parse_args()


def load_attempt_log(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def append_attempt_log(path: Path, entry: dict) -> None:
    ensure_dir(path.parent)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


def generate_clip_replacement_images(
    run_id: str,
    *,
    prompt: str,
    profile: str | None = None,
    url: str = "https://chatgpt.com/",
    timeout_ms: int = 180000,
    max_retries: int = 3,
    headless: bool = False,
    overwrite: bool = False,
) -> tuple[int, int]:
    run_dir = get_run_dir(run_id)
    modified_frames_dir = ensure_dir(run_dir / "modified_frames")
    logs_dir = ensure_dir(run_dir / "logs")
    attempts_log_path = logs_dir / "clip-image-generation.jsonl"

    run_manifest = load_run_manifest(run_id)
    clips_manifest = load_clips_manifest(run_id)
    clips = clips_manifest.get("clips", [])
    if not clips:
        raise ValueError("No clips found for this run.")

    success_count = 0
    failure_count = 0

    for clip in clips:
        clip_id = clip["clip_id"]
        first_frame_path = clip.get("first_frame_path")
        if not first_frame_path:
            raise ValueError(f"Clip {clip_id} does not have a first_frame_path.")

        output_path = modified_frames_dir / f"{clip_id}.png"
        if output_path.exists() and not overwrite:
            clip["modified_frame_path"] = str(output_path)
            clip["modified_frame_status"] = "completed"
            success_count += 1
            continue

        last_error: str | None = None
        for attempt in range(1, max_retries + 1):
            debug_dir = logs_dir / "chatgpt" / clip_id / f"attempt_{attempt:02d}"
            try:
                generated_path = generate_image(
                    prompt=prompt,
                    output=str(output_path),
                    images=[first_frame_path],
                    profile=profile,
                    url=url,
                    timeout_ms=timeout_ms,
                    headless=headless,
                    debug_dir=str(debug_dir),
                )
                clip["modified_frame_path"] = str(generated_path)
                clip["modified_frame_status"] = "completed"
                clip["modified_frame_attempts"] = attempt
                clip.pop("modified_frame_error", None)
                save_clips_manifest(run_id, clips_manifest)
                append_attempt_log(
                    attempts_log_path,
                    {
                        "timestamp": timestamp_utc(),
                        "run_id": run_id,
                        "clip_id": clip_id,
                        "attempt": attempt,
                        "status": "success",
                        "output_path": str(generated_path),
                    },
                )
                success_count += 1
                last_error = None
                break
            except Exception as exc:
                last_error = str(exc)
                append_attempt_log(
                    attempts_log_path,
                    {
                        "timestamp": timestamp_utc(),
                        "run_id": run_id,
                        "clip_id": clip_id,
                        "attempt": attempt,
                        "status": "error",
                        "error": last_error,
                    },
                )

        if last_error is not None:
            clip["modified_frame_status"] = "failed"
            clip["modified_frame_attempts"] = max_retries
            clip["modified_frame_error"] = last_error
            save_clips_manifest(run_id, clips_manifest)
            failure_count += 1

    save_clips_manifest(run_id, clips_manifest)

    summary = {
        "run_id": run_id,
        "prompt": prompt,
        "success_count": success_count,
        "failure_count": failure_count,
        "max_retries": max_retries,
        "completed_at": timestamp_utc(),
    }
    save_json(run_dir / "output" / "clip-replacement-images.json", summary)

    run_manifest.setdefault("steps", {})
    run_manifest["steps"]["generate_clip_replacement_images"] = {
        "status": "completed" if failure_count == 0 else "completed_with_failures",
        "updated_at": None,
        "success_count": success_count,
        "failure_count": failure_count,
    }
    run_manifest["status"] = "replacement_images_generated" if failure_count == 0 else "replacement_images_partial"
    save_run_manifest(run_id, run_manifest)
    run_manifest = load_run_manifest(run_id)
    run_manifest["steps"]["generate_clip_replacement_images"]["updated_at"] = run_manifest["updated_at"]
    save_run_manifest(run_id, run_manifest)

    return success_count, failure_count


def main() -> None:
    args = parse_args()
    success_count, failure_count = generate_clip_replacement_images(
        args.run_id,
        prompt=args.prompt,
        profile=args.profile,
        url=args.url,
        timeout_ms=args.timeout_ms,
        max_retries=args.max_retries,
        headless=args.headless,
        overwrite=args.overwrite,
    )
    print(f"Run ID: {args.run_id}")
    print(f"Generated replacement images: {success_count}")
    print(f"Failed replacement images: {failure_count}")
    print(f"Output directory: {get_run_dir(args.run_id) / 'modified_frames'}")


if __name__ == "__main__":
    main()
