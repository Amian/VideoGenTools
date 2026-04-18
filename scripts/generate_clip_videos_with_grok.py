#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path

from grok_video_generation import generate_video
from lib.common import ensure_dir, save_json, timestamp_utc
from lib.pipeline import get_run_dir, load_clips_manifest, load_run_manifest, save_clips_manifest, save_run_manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate one Grok video per clip, sequentially, so each downloaded video maps to a known clip."
    )
    parser.add_argument("--run-id", required=True, help="Existing run identifier.")
    parser.add_argument(
        "--prompt",
        help="Optional shared video prompt. If omitted, uses each clip's recreation_prompt from clips.json.",
    )
    parser.add_argument(
        "--use-first-frames",
        action="store_true",
        help="Use first_frame_path instead of modified_frame_path as the reference image.",
    )
    parser.add_argument("--profile", help="Optional Playwright/Chrome profile directory.")
    parser.add_argument("--url", default="https://grok.com/imagine", help="Grok Imagine URL.")
    parser.add_argument(
        "--saved-url",
        default="https://grok.com/imagine/saved",
        help="Grok Imagine Saved URL used to retrieve finished videos.",
    )
    parser.add_argument("--timeout-ms", type=int, default=420000, help="Per-video timeout in milliseconds.")
    parser.add_argument("--max-retries", type=int, default=3, help="Maximum attempts per clip.")
    parser.add_argument("--headless", action="store_true", help="Run Playwright headless.")
    parser.add_argument("--overwrite", action="store_true", help="Regenerate videos even if they already exist.")
    return parser.parse_args()


def append_attempt_log(path: Path, entry: dict) -> None:
    ensure_dir(path.parent)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


def choose_reference_image(clip: dict, use_first_frames: bool) -> str:
    if use_first_frames:
        first_frame_path = clip.get("first_frame_path")
        if not first_frame_path:
            raise ValueError(f"Clip {clip['clip_id']} is missing first_frame_path.")
        return first_frame_path

    modified_frame_path = clip.get("modified_frame_path")
    if modified_frame_path:
        return modified_frame_path

    first_frame_path = clip.get("first_frame_path")
    if first_frame_path:
        return first_frame_path

    raise ValueError(f"Clip {clip['clip_id']} is missing both modified_frame_path and first_frame_path.")


def choose_prompt(clip: dict, shared_prompt: str | None) -> str:
    if shared_prompt:
        return shared_prompt

    recreation_prompt = clip.get("recreation_prompt")
    if recreation_prompt:
        return recreation_prompt

    raise ValueError(f"Clip {clip['clip_id']} is missing recreation_prompt and no shared --prompt was provided.")


def generate_clip_videos_with_grok(
    run_id: str,
    *,
    prompt: str | None = None,
    use_first_frames: bool = False,
    profile: str | None = None,
    url: str = "https://grok.com/imagine",
    saved_url: str = "https://grok.com/imagine/saved",
    timeout_ms: int = 420000,
    max_retries: int = 3,
    headless: bool = False,
    overwrite: bool = False,
) -> tuple[int, int]:
    run_dir = get_run_dir(run_id)
    animations_dir = ensure_dir(run_dir / "animations")
    logs_dir = ensure_dir(run_dir / "logs")
    debug_root = ensure_dir(logs_dir / "grok")
    attempts_log_path = logs_dir / "clip-video-generation.jsonl"

    run_manifest = load_run_manifest(run_id)
    clips_manifest = load_clips_manifest(run_id)
    clips = clips_manifest.get("clips", [])
    if not clips:
        raise ValueError("No clips found for this run.")

    success_count = 0
    failure_count = 0

    for index, clip in enumerate(clips, start=1):
        clip_id = clip["clip_id"]
        prompt_text = choose_prompt(clip, prompt)
        reference_image = choose_reference_image(clip, use_first_frames)
        output_path = animations_dir / f"{clip_id}.mp4"

        if output_path.exists() and not overwrite:
            clip["generated_video_path"] = str(output_path)
            clip["generated_video_status"] = "completed"
            clip["generated_video_attempts"] = clip.get("generated_video_attempts", 0)
            save_clips_manifest(run_id, clips_manifest)
            success_count += 1
            continue

        last_error: str | None = None
        for attempt in range(1, max_retries + 1):
            debug_dir = debug_root / clip_id / f"attempt_{attempt:02d}"
            try:
                generated_path = generate_video(
                    prompt=prompt_text,
                    output=str(output_path),
                    images=[reference_image],
                    profile=profile,
                    url=url,
                    saved_url=saved_url,
                    timeout_ms=timeout_ms,
                    headless=headless,
                    debug_dir=str(debug_dir),
                )
                clip["generated_video_path"] = str(generated_path)
                clip["generated_video_status"] = "completed"
                clip["generated_video_attempts"] = attempt
                clip["generated_video_prompt"] = prompt_text
                clip["generated_video_reference_image"] = reference_image
                clip["generated_video_sequence"] = index
                clip.pop("generated_video_error", None)
                save_clips_manifest(run_id, clips_manifest)
                append_attempt_log(
                    attempts_log_path,
                    {
                        "timestamp": timestamp_utc(),
                        "run_id": run_id,
                        "clip_id": clip_id,
                        "sequence": index,
                        "attempt": attempt,
                        "status": "success",
                        "output_path": str(generated_path),
                        "reference_image": reference_image,
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
                        "sequence": index,
                        "attempt": attempt,
                        "status": "error",
                        "error": last_error,
                        "reference_image": reference_image,
                    },
                )

        if last_error is not None:
            clip["generated_video_status"] = "failed"
            clip["generated_video_attempts"] = max_retries
            clip["generated_video_error"] = last_error
            clip["generated_video_prompt"] = prompt_text
            clip["generated_video_reference_image"] = reference_image
            clip["generated_video_sequence"] = index
            save_clips_manifest(run_id, clips_manifest)
            failure_count += 1

    save_clips_manifest(run_id, clips_manifest)

    summary = {
        "run_id": run_id,
        "success_count": success_count,
        "failure_count": failure_count,
        "max_retries": max_retries,
        "saved_url": saved_url,
        "completed_at": timestamp_utc(),
    }
    save_json(run_dir / "output" / "clip-videos-grok.json", summary)

    run_manifest.setdefault("steps", {})
    run_manifest["steps"]["generate_clip_videos_with_grok"] = {
        "status": "completed" if failure_count == 0 else "completed_with_failures",
        "updated_at": None,
        "success_count": success_count,
        "failure_count": failure_count,
    }
    run_manifest["status"] = "clip_videos_generated" if failure_count == 0 else "clip_videos_partial"
    save_run_manifest(run_id, run_manifest)
    run_manifest = load_run_manifest(run_id)
    run_manifest["steps"]["generate_clip_videos_with_grok"]["updated_at"] = run_manifest["updated_at"]
    save_run_manifest(run_id, run_manifest)

    return success_count, failure_count


def main() -> None:
    args = parse_args()
    success_count, failure_count = generate_clip_videos_with_grok(
        args.run_id,
        prompt=args.prompt,
        use_first_frames=args.use_first_frames,
        profile=args.profile,
        url=args.url,
        saved_url=args.saved_url,
        timeout_ms=args.timeout_ms,
        max_retries=args.max_retries,
        headless=args.headless,
        overwrite=args.overwrite,
    )
    print(f"Run ID: {args.run_id}")
    print(f"Generated clip videos: {success_count}")
    print(f"Failed clip videos: {failure_count}")
    print(f"Output directory: {get_run_dir(args.run_id) / 'animations'}")


if __name__ == "__main__":
    main()
