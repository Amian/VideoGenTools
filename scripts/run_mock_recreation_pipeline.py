#!/usr/bin/env python3

from __future__ import annotations

import argparse

from analyze_video_with_gemini import analyze_video_with_gemini
from assemble_final_video import assemble_final_video
from detect_scenes import detect_scenes
from export_clip_boundaries import export_clip_boundaries
from extract_all_first_frames import extract_all_first_frames
from generate_clip_replacement_images import (
    DEFAULT_REPLACEMENT_IMAGE_PROMPT,
    generate_clip_replacement_images,
)
from generate_clip_videos_with_grok import generate_clip_videos_with_grok
from ingest_video import ingest_video
from lib.pipeline import get_run_dir
from setup_run import setup_run


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the full local/mock recreation pipeline from source video to a final concatenated recreated video."
    )
    parser.add_argument("--source-video", required=True, help="Path to the source video.")
    parser.add_argument("--run-id", help="Optional explicit run identifier.")
    parser.add_argument("--run-name", help="Optional display name for the run.")
    parser.add_argument("--threshold", type=float, default=0.35, help="FFmpeg scene detection threshold.")
    parser.add_argument(
        "--min-scene-length",
        type=float,
        default=0.75,
        help="Minimum number of seconds between detected clip starts.",
    )
    parser.add_argument(
        "--mock-response-file",
        help="Optional mock Gemini JSON response file. Defaults to samples/sample-clip-definition.json.",
    )
    parser.add_argument(
        "--replacement-image-prompt",
        default=DEFAULT_REPLACEMENT_IMAGE_PROMPT,
        help="Shared prompt used to generate replacement first-frame images.",
    )
    parser.add_argument(
        "--symlink-input",
        action="store_true",
        help="Symlink the source video into the run folder instead of copying it.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite replacement images, Grok clip videos, normalized clips, and final output if they exist.",
    )
    parser.add_argument(
        "--use-source-audio",
        action="store_true",
        help="Mux the source audio onto the final recreated video if the input video contains audio.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    run_id = setup_run(args.source_video, run_id=args.run_id, run_name=args.run_name)
    ingest_video(run_id, mode="symlink" if args.symlink_input else "copy")
    detect_scenes(run_id, threshold=args.threshold, min_scene_length=args.min_scene_length)
    extract_all_first_frames(run_id, overwrite=args.overwrite)
    export_clip_boundaries(run_id)

    analyze_video_with_gemini(
        run_id,
        use_mock=True,
        mock_response_file=args.mock_response_file,
    )

    image_success_count, image_failure_count = generate_clip_replacement_images(
        run_id,
        prompt=args.replacement_image_prompt,
        overwrite=args.overwrite,
    )
    if image_failure_count:
        raise RuntimeError(
            f"Replacement image generation failed for {image_failure_count} clips in run {run_id}."
        )

    video_success_count, video_failure_count = generate_clip_videos_with_grok(
        run_id,
        overwrite=args.overwrite,
    )
    if video_failure_count:
        raise RuntimeError(
            f"Grok video generation failed for {video_failure_count} clips in run {run_id}."
        )

    final_output_path = assemble_final_video(
        run_id,
        use_source_audio=args.use_source_audio,
        overwrite=args.overwrite,
    )

    print(f"Run ID: {run_id}")
    print(f"Replacement images: {image_success_count}")
    print(f"Grok videos: {video_success_count}")
    print(f"Run directory: {get_run_dir(run_id)}")
    print(f"Final recreated video: {final_output_path}")


if __name__ == "__main__":
    main()
