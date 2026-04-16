from __future__ import annotations

import argparse
from pathlib import Path

from lib.gemini_video import (
    CLIP_ANALYSIS_SCHEMA,
    DEFAULT_GEMINI_MODEL,
    GEMINI_CLIP_ANALYSIS_PROMPT,
    build_clips_manifest_from_gemini,
    env_flag,
    extract_response_text,
    get_gemini_client,
    get_mock_response_path,
    parse_clip_analysis_json,
    save_gemini_artifacts,
    wait_for_uploaded_file,
)
from lib.pipeline import get_run_dir, load_clips_manifest, load_run_manifest, save_clips_manifest, save_run_manifest


def analyze_video_with_gemini(
    run_id: str,
    *,
    model: str = DEFAULT_GEMINI_MODEL,
    prompt_text: str = GEMINI_CLIP_ANALYSIS_PROMPT,
    poll_interval_seconds: float = 5.0,
    keep_remote_file: bool = False,
    use_mock: bool | None = None,
    mock_response_file: str | None = None,
) -> dict:
    run_manifest = load_run_manifest(run_id)
    input_video = run_manifest.get("input_video")
    if not input_video:
        raise ValueError("Run does not have an ingested input video yet.")

    input_path = Path(input_video)
    if not input_path.is_file():
        raise FileNotFoundError(f"Ingested video not found: {input_path}")

    resolved_use_mock = env_flag("GEMINI_USE_MOCK", default=False) if use_mock is None else use_mock
    remote_file_name: str | None = None

    if resolved_use_mock:
        mock_path = get_mock_response_path(mock_response_file)
        if not mock_path.is_file():
            raise FileNotFoundError(f"Mock Gemini response file not found: {mock_path}")
        response_text = mock_path.read_text(encoding="utf-8")
        gemini_json = parse_clip_analysis_json(response_text)
        model_name = f"{model} (mock)"
    else:
        client = get_gemini_client()
        uploaded = client.files.upload(file=str(input_path))
        uploaded = wait_for_uploaded_file(client, uploaded.name, poll_interval_seconds=poll_interval_seconds)

        response = client.models.generate_content(
            model=model,
            contents=[uploaded, prompt_text],
            config={
                "response_mime_type": "application/json",
                "response_json_schema": CLIP_ANALYSIS_SCHEMA,
            },
        )
        response_text = extract_response_text(response)
        gemini_json = parse_clip_analysis_json(response_text)
        remote_file_name = uploaded.name
        model_name = model

    existing_clips_manifest = load_clips_manifest(run_id)
    clips_manifest = build_clips_manifest_from_gemini(
        run_id,
        existing_clips_manifest.get("created_at"),
        gemini_json,
        model=model_name,
    )
    save_clips_manifest(run_id, clips_manifest)
    save_gemini_artifacts(
        get_run_dir(run_id),
        prompt_text=prompt_text,
        raw_response_text=response_text,
        normalized_response=gemini_json,
    )

    run_manifest["status"] = "gemini_analyzed"
    run_manifest["clip_count"] = gemini_json["total_clips"]
    run_manifest.setdefault("steps", {})
    run_manifest["steps"]["analyze_video_with_gemini"] = {
        "status": "completed",
        "updated_at": None,
        "model": model_name,
        "remote_file_name": remote_file_name,
        "used_mock": resolved_use_mock,
    }
    save_run_manifest(run_id, run_manifest)
    run_manifest = load_run_manifest(run_id)
    run_manifest["steps"]["analyze_video_with_gemini"]["updated_at"] = run_manifest["updated_at"]
    save_run_manifest(run_id, run_manifest)

    if not resolved_use_mock and not keep_remote_file:
        client.files.delete(name=uploaded.name)

    return gemini_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze an ingested video with Gemini and produce clips.json.")
    parser.add_argument("--run-id", required=True, help="Run identifier.")
    parser.add_argument("--model", default=DEFAULT_GEMINI_MODEL, help="Gemini model name.")
    parser.add_argument(
        "--prompt-file",
        help="Optional path to a custom Gemini prompt. Defaults to the built-in clip analysis prompt.",
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=float,
        default=5.0,
        help="How often to poll Gemini Files API while the uploaded video is processing.",
    )
    parser.add_argument(
        "--keep-remote-file",
        action="store_true",
        help="Do not delete the uploaded Gemini file after the response is saved.",
    )
    parser.add_argument(
        "--use-mock",
        action="store_true",
        help="Skip Gemini API calls and load the response from a local JSON file instead.",
    )
    parser.add_argument(
        "--mock-response-file",
        help="Path to a mock Gemini JSON response file. Defaults to samples/sample-clip-definition.json.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    prompt_text = GEMINI_CLIP_ANALYSIS_PROMPT
    if args.prompt_file:
        prompt_text = Path(args.prompt_file).read_text(encoding="utf-8")

    result = analyze_video_with_gemini(
        args.run_id,
        model=args.model,
        prompt_text=prompt_text,
        poll_interval_seconds=args.poll_interval_seconds,
        keep_remote_file=args.keep_remote_file,
        use_mock=args.use_mock if args.use_mock else None,
        mock_response_file=args.mock_response_file,
    )

    print(f"Run ID: {args.run_id}")
    print(f"Gemini clips: {result['total_clips']}")
    print(f"Manifest: {get_run_dir(args.run_id) / 'manifests' / 'clips.json'}")


if __name__ == "__main__":
    main()
