from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from .common import ROOT_DIR, save_json, timestamp_utc


DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"

GEMINI_CLIP_ANALYSIS_PROMPT = """You are analyzing a video for automated clip-by-clip recreation.

Split the video into meaningful clips based on shot changes, scene cuts, major camera changes, or major action changes. Do not split minor motion inside the same shot.

For each clip, return:
- clip_number
- start_time_seconds
- duration_seconds
- end_time_seconds
- short_action_summary
- recreation_prompt

The output will be used in this pipeline:
1. the first frame of each clip is extracted,
2. that frame is rewritten into a more original version,
3. a video generation model receives that first frame plus your recreation_prompt to recreate the clip.

So the recreation_prompt must be written for video generation, not for analysis.

For each recreation_prompt:
- describe what is visibly happening in the clip
- describe how the motion develops from the first frame through the clip
- include subject, action, setting, background, framing, camera angle, camera movement, lighting, mood, important objects, and motion details
- keep it direct, visual, and practical
- do not be vague
- do not add unsupported details
- keep each recreation_prompt between 50 and 120 words

For short_action_summary:
- use 1 short sentence only

Round all times to 2 decimal places.

Return ONLY valid JSON in this exact format:

{
  "total_clips": 0,
  "clips": [
    {
      "clip_number": 1,
      "start_time_seconds": 0.0,
      "duration_seconds": 0.0,
      "end_time_seconds": 0.0,
      "short_action_summary": "",
      "recreation_prompt": ""
    }
  ]
}"""

CLIP_ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "propertyOrdering": ["total_clips", "clips"],
    "required": ["total_clips", "clips"],
    "properties": {
        "total_clips": {"type": "integer"},
        "clips": {
            "type": "array",
            "items": {
                "type": "object",
                "propertyOrdering": [
                    "clip_number",
                    "start_time_seconds",
                    "duration_seconds",
                    "end_time_seconds",
                    "short_action_summary",
                    "recreation_prompt",
                ],
                "required": [
                    "clip_number",
                    "start_time_seconds",
                    "duration_seconds",
                    "end_time_seconds",
                    "short_action_summary",
                    "recreation_prompt",
                ],
                "properties": {
                    "clip_number": {"type": "integer"},
                    "start_time_seconds": {"type": "number"},
                    "duration_seconds": {"type": "number"},
                    "end_time_seconds": {"type": "number"},
                    "short_action_summary": {"type": "string"},
                    "recreation_prompt": {"type": "string"},
                },
            },
        },
    },
}


def get_gemini_client(api_key: str | None = None):
    try:
        from google import genai
    except ImportError as exc:
        raise RuntimeError(
            "The google-genai package is required. Install it with: python3 -m pip install google-genai"
        ) from exc

    resolved_api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not resolved_api_key:
        raise RuntimeError("GEMINI_API_KEY is not set.")
    return genai.Client(api_key=resolved_api_key)


def env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def get_mock_response_path(explicit_path: str | None = None) -> Path:
    path_value = explicit_path or os.environ.get("GEMINI_MOCK_RESPONSE_FILE")
    if not path_value:
        return ROOT_DIR / "samples" / "sample-clip-definition.json"
    return Path(path_value).expanduser().resolve()


def wait_for_uploaded_file(client: Any, file_name: str, poll_interval_seconds: float = 5.0) -> Any:
    uploaded = client.files.get(name=file_name)
    while True:
        state = getattr(uploaded, "state", None)
        state_name = getattr(state, "name", None) or str(state or "")
        if state_name == "ACTIVE":
            return uploaded
        if state_name == "FAILED":
            raise RuntimeError(f"Gemini file processing failed for {file_name}")
        time.sleep(poll_interval_seconds)
        uploaded = client.files.get(name=file_name)


def extract_response_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if text:
        return text

    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            part_text = getattr(part, "text", None)
            if part_text:
                return part_text
    raise RuntimeError("Gemini response did not contain text output.")


def parse_clip_analysis_json(response_text: str) -> dict[str, Any]:
    text = response_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].startswith("```"):
            text = "\n".join(lines[1:-1]).strip()

    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("Gemini output was not a JSON object.")

    clips = parsed.get("clips")
    if not isinstance(clips, list):
        raise ValueError("Gemini output did not include a clips array.")

    normalized_clips: list[dict[str, Any]] = []
    for clip in clips:
        clip_number = int(clip["clip_number"])
        start_time = round(float(clip["start_time_seconds"]), 2)
        duration = round(float(clip["duration_seconds"]), 2)
        end_time = round(float(clip["end_time_seconds"]), 2)
        normalized_clips.append(
            {
                "clip_number": clip_number,
                "start_time_seconds": start_time,
                "duration_seconds": duration,
                "end_time_seconds": end_time,
                "short_action_summary": str(clip["short_action_summary"]).strip(),
                "recreation_prompt": str(clip["recreation_prompt"]).strip(),
            }
        )
    normalized_clips.sort(key=lambda item: item["clip_number"])

    return {
        "total_clips": len(normalized_clips),
        "clips": normalized_clips,
    }


def save_gemini_artifacts(
    run_dir: Path,
    *,
    prompt_text: str,
    raw_response_text: str,
    normalized_response: dict[str, Any],
) -> None:
    manifests_dir = run_dir / "manifests"
    prompts_dir = run_dir / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    manifests_dir.mkdir(parents=True, exist_ok=True)

    (prompts_dir / "gemini_clip_analysis_prompt.txt").write_text(prompt_text, encoding="utf-8")
    (manifests_dir / "gemini_raw_response.json").write_text(raw_response_text, encoding="utf-8")
    save_json(manifests_dir / "gemini_clip_analysis.json", normalized_response)


def build_clips_manifest_from_gemini(
    run_id: str,
    existing_created_at: str | None,
    gemini_json: dict[str, Any],
    *,
    model: str,
) -> dict[str, Any]:
    clips = []
    for clip in gemini_json["clips"]:
        clip_number = int(clip["clip_number"])
        start_time = round(float(clip["start_time_seconds"]), 2)
        end_time = round(float(clip["end_time_seconds"]), 2)
        duration = round(float(clip["duration_seconds"]), 2)
        clip_id = f"clip_{clip_number:04d}"
        clips.append(
            {
                "clip_id": clip_id,
                "index": clip_number,
                "clip_number": clip_number,
                "start_time": start_time,
                "start_time_seconds": start_time,
                "duration_seconds": duration,
                "end_time": end_time,
                "end_time_seconds": end_time,
                "short_action_summary": clip["short_action_summary"],
                "recreation_prompt": clip["recreation_prompt"],
                "clip_path": None,
                "analysis_path": None,
                "first_frame_path": None,
                "status": "gemini_analyzed",
            }
        )

    return {
        "run_id": run_id,
        "created_at": existing_created_at or timestamp_utc(),
        "source": "gemini_video_analysis",
        "model": model,
        "total_clips": len(clips),
        "clips": clips,
    }
