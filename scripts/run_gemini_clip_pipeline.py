from __future__ import annotations

import argparse

from analyze_video_with_gemini import analyze_video_with_gemini
from extract_all_first_frames import extract_all_first_frames
from ingest_video import ingest_video
from lib.pipeline import get_run_dir
from setup_run import setup_run


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Gemini clip-analysis pipeline from source video to clip-start frame images."
    )
    parser.add_argument("--source-video", required=True, help="Path to the source video.")
    parser.add_argument("--run-id", help="Optional explicit run identifier.")
    parser.add_argument("--run-name", help="Optional display name for the run.")
    parser.add_argument("--model", default="gemini-2.5-flash", help="Gemini model name.")
    parser.add_argument(
        "--poll-interval-seconds",
        type=float,
        default=5.0,
        help="How often to poll Gemini while the uploaded video is processing.",
    )
    parser.add_argument(
        "--keep-remote-file",
        action="store_true",
        help="Do not delete the uploaded Gemini file after processing.",
    )
    parser.add_argument(
        "--use-mock",
        action="store_true",
        help="Skip Gemini API calls and use the configured mock Gemini JSON instead.",
    )
    parser.add_argument(
        "--mock-response-file",
        help="Path to a mock Gemini JSON response file. Defaults to samples/sample-clip-definition.json.",
    )
    parser.add_argument(
        "--symlink-input",
        action="store_true",
        help="Symlink the source video into the run folder instead of copying it.",
    )
    parser.add_argument("--overwrite-frames", action="store_true", help="Rebuild first-frame images if they exist.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    run_id = setup_run(args.source_video, run_id=args.run_id, run_name=args.run_name)
    ingest_video(run_id, mode="symlink" if args.symlink_input else "copy")
    analysis = analyze_video_with_gemini(
        run_id,
        model=args.model,
        poll_interval_seconds=args.poll_interval_seconds,
        keep_remote_file=args.keep_remote_file,
        use_mock=args.use_mock if args.use_mock else None,
        mock_response_file=args.mock_response_file,
    )
    frame_count = extract_all_first_frames(run_id, overwrite=args.overwrite_frames)

    print(f"Run ID: {run_id}")
    print(f"Gemini clips: {analysis['total_clips']}")
    print(f"Extracted first frames: {frame_count}")
    print(f"Frames directory: {get_run_dir(run_id) / 'frames'}")


if __name__ == "__main__":
    main()
