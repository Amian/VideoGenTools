#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path

from lib.common import ensure_dir, get_video_metadata, run_command, save_json, timestamp_utc
from lib.pipeline import get_run_dir, load_clips_manifest, load_run_manifest, save_clips_manifest, save_run_manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Trim regenerated clip videos to their manifest durations and concatenate them into a final recreated video."
    )
    parser.add_argument("--run-id", required=True, help="Existing run identifier.")
    parser.add_argument("--output", help="Optional explicit final output path. Defaults to run output/final-recreated-video.mp4.")
    parser.add_argument(
        "--use-source-audio",
        action="store_true",
        help="Mux the original source audio onto the final recreated video if the source video has an audio stream.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Rebuild normalized clip videos and the final output even if they already exist.",
    )
    return parser.parse_args()


def resolve_final_output_path(run_id: str, output_arg: str | None) -> Path:
    if output_arg:
        return Path(output_arg).expanduser().resolve()
    return get_run_dir(run_id) / "output" / "final-recreated-video.mp4"


def normalize_clip_video(
    input_path: Path,
    output_path: Path,
    *,
    duration_seconds: float,
    width: int,
    height: int,
    fps: float | None,
    overwrite: bool,
) -> None:
    if output_path.exists() and not overwrite:
        return

    fps_value = fps or 30.0
    run_command(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-t",
            f"{duration_seconds:.3f}",
            "-vf",
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,fps={fps_value:.3f}",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            str(output_path),
        ]
    )


def maybe_mux_source_audio(
    *,
    video_path: Path,
    source_video_path: Path,
    output_path: Path,
    overwrite: bool,
) -> Path:
    if output_path.exists() and not overwrite:
        return output_path

    run_command(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-i",
            str(source_video_path),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            str(output_path),
        ]
    )
    return output_path


def assemble_final_video(
    run_id: str,
    *,
    output: str | None = None,
    use_source_audio: bool = False,
    overwrite: bool = False,
) -> Path:
    run_dir = get_run_dir(run_id)
    run_manifest = load_run_manifest(run_id)
    clips_manifest = load_clips_manifest(run_id)
    clips = clips_manifest.get("clips", [])
    if not clips:
        raise ValueError("No clips found for this run.")

    input_video = run_manifest.get("input_video")
    if not input_video:
        raise ValueError("Run does not have an ingested input video.")

    source_video_path = Path(input_video)
    source_metadata = get_video_metadata(source_video_path)
    width = int(source_metadata["video"]["width"] or 1024)
    height = int(source_metadata["video"]["height"] or 1024)
    fps = source_metadata["video"].get("fps") or 30.0

    normalized_dir = ensure_dir(run_dir / "output" / "normalized_clips")
    concat_list_path = run_dir / "output" / "concat-list.txt"
    final_output_path = resolve_final_output_path(run_id, output)
    ensure_dir(final_output_path.parent)

    normalized_paths: list[Path] = []
    for clip in clips:
        generated_video_path = clip.get("generated_video_path")
        if not generated_video_path:
            raise ValueError(f"Clip {clip['clip_id']} is missing generated_video_path.")
        input_path = Path(generated_video_path)
        if not input_path.is_file():
            raise FileNotFoundError(f"Generated clip video not found: {input_path}")

        normalized_path = normalized_dir / f"{clip['clip_id']}.mp4"
        normalize_clip_video(
            input_path,
            normalized_path,
            duration_seconds=float(clip["duration_seconds"]),
            width=width,
            height=height,
            fps=fps,
            overwrite=overwrite,
        )
        clip["normalized_video_path"] = str(normalized_path)
        normalized_paths.append(normalized_path)

    concat_list_path.write_text(
        "".join(f"file '{path.as_posix()}'\n" for path in normalized_paths),
        encoding="utf-8",
    )

    run_command(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list_path),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(final_output_path),
        ]
    )

    completed_output_path = final_output_path
    if use_source_audio and source_metadata.get("audio"):
        audio_output_path = final_output_path.with_name(f"{final_output_path.stem}-with-audio{final_output_path.suffix}")
        completed_output_path = maybe_mux_source_audio(
            video_path=final_output_path,
            source_video_path=source_video_path,
            output_path=audio_output_path,
            overwrite=overwrite,
        )

    save_clips_manifest(run_id, clips_manifest)

    summary = {
        "run_id": run_id,
        "final_output_path": str(completed_output_path),
        "base_video_output_path": str(final_output_path),
        "used_source_audio": use_source_audio and bool(source_metadata.get("audio")),
        "clip_count": len(clips),
        "completed_at": timestamp_utc(),
    }
    save_json(run_dir / "output" / "final-video-summary.json", summary)

    run_manifest.setdefault("steps", {})
    run_manifest["steps"]["assemble_final_video"] = {
        "status": "completed",
        "updated_at": None,
        "output_path": str(completed_output_path),
    }
    run_manifest["status"] = "final_video_assembled"
    run_manifest["final_output_path"] = str(completed_output_path)
    save_run_manifest(run_id, run_manifest)
    run_manifest = load_run_manifest(run_id)
    run_manifest["steps"]["assemble_final_video"]["updated_at"] = run_manifest["updated_at"]
    save_run_manifest(run_id, run_manifest)

    return completed_output_path


def main() -> None:
    args = parse_args()
    output_path = assemble_final_video(
        args.run_id,
        output=args.output,
        use_source_audio=args.use_source_audio,
        overwrite=args.overwrite,
    )
    print(f"Run ID: {args.run_id}")
    print(f"Final output: {output_path}")


if __name__ == "__main__":
    main()
