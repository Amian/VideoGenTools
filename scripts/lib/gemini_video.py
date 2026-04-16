from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from .common import ROOT_DIR, save_json, timestamp_utc


DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"

GEMINI_CLIP_ANALYSIS_PROMPT_TEMPLATE = """You are analyzing a video for automated clip-by-clip recreation.

The clip boundaries have already been determined locally by script. Use those boundaries exactly as given. Do not create new clips, remove clips, merge clips, or change clip numbering.

For each provided clip boundary, analyze only that time span and return:
- clip_number
- short_action_summary
- recreation_prompt

The output will be used in this pipeline:
1. the first frame of each clip is already extracted from the provided start boundary,
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

Here are the exact clip boundaries you must use:

{boundary_json}

Return ONLY valid JSON in this exact format:

{{
  "total_clips": 0,
  "clips": [
    {{
      "clip_number": 1,
      "short_action_summary": "",
      "recreation_prompt": ""
    }}
  ]
}}"""

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
                    "short_action_summary",
                    "recreation_prompt",
                ],
                "required": [
                    "clip_number",
                    "short_action_summary",
                    "recreation_prompt",
                ],
                "properties": {
                    "clip_number": {"type": "integer"},
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


def build_boundary_context(clips_manifest: dict[str, Any]) -> str:
    payload = {
        "total_clips": len(clips_manifest.get("clips", [])),
        "clips": [],
    }
    for clip in clips_manifest.get("clips", []):
        payload["clips"].append(
            {
                "clip_number": int(clip.get("clip_number") or clip["index"]),
                "start_time_seconds": round(float(clip.get("start_time_seconds", clip["start_time"])), 3),
                "duration_seconds": round(float(clip["duration_seconds"]), 3),
                "end_time_seconds": round(float(clip.get("end_time_seconds", clip["end_time"])), 3),
            }
        )
    return json.dumps(payload, indent=2)


def build_clip_prompt_from_boundaries(clips_manifest: dict[str, Any]) -> str:
    return GEMINI_CLIP_ANALYSIS_PROMPT_TEMPLATE.format(
        boundary_json=build_boundary_context(clips_manifest)
    )


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
        normalized_clips.append(
            {
                "clip_number": clip_number,
                "short_action_summary": str(clip["short_action_summary"]).strip(),
                "recreation_prompt": str(clip["recreation_prompt"]).strip(),
            }
        )
    normalized_clips.sort(key=lambda item: item["clip_number"])

    return {
        "total_clips": len(normalized_clips),
        "clips": normalized_clips,
    }


def fit_mock_response_to_boundaries(
    mock_response: dict[str, Any],
    clips_manifest: dict[str, Any],
) -> dict[str, Any]:
    local_clips = clips_manifest.get("clips", [])
    if not local_clips:
        return {"total_clips": 0, "clips": []}

    mock_clips = mock_response.get("clips", [])
    if not mock_clips:
        raise ValueError("Mock Gemini response does not include any clips.")

    if len(mock_clips) == len(local_clips):
        return {
            "total_clips": len(mock_clips),
            "clips": [
                {
                    "clip_number": int(local_clip.get("clip_number") or local_clip["index"]),
                    "short_action_summary": mock_clip["short_action_summary"],
                    "recreation_prompt": mock_clip["recreation_prompt"],
                }
                for local_clip, mock_clip in zip(local_clips, mock_clips)
            ],
        }

    fitted_clips: list[dict[str, Any]] = []
    for index, local_clip in enumerate(local_clips):
        template_clip = mock_clips[index % len(mock_clips)]
        fitted_clips.append(
            {
                "clip_number": int(local_clip.get("clip_number") or local_clip["index"]),
                "short_action_summary": template_clip["short_action_summary"],
                "recreation_prompt": template_clip["recreation_prompt"],
            }
        )

    return {
        "total_clips": len(fitted_clips),
        "clips": fitted_clips,
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
    existing_manifest: dict[str, Any],
    gemini_json: dict[str, Any],
    *,
    model: str,
) -> dict[str, Any]:
    clips_by_number = {
        int(clip.get("clip_number") or clip["index"]): dict(clip)
        for clip in existing_manifest.get("clips", [])
    }
    for clip in gemini_json["clips"]:
        clip_number = int(clip["clip_number"])
        if clip_number not in clips_by_number:
            raise KeyError(f"Gemini returned clip_number {clip_number}, which does not exist in the local clips manifest.")
        existing_clip = clips_by_number[clip_number]
        existing_clip["short_action_summary"] = clip["short_action_summary"]
        existing_clip["recreation_prompt"] = clip["recreation_prompt"]
        existing_clip["status"] = "gemini_analyzed"
        clips_by_number[clip_number] = existing_clip

    merged_clips = [
        clips_by_number[key]
        for key in sorted(clips_by_number.keys())
    ]

    merged_manifest = {
        "run_id": run_id,
        "created_at": existing_manifest.get("created_at") or timestamp_utc(),
        "source": existing_manifest.get("source", "gemini_video_analysis"),
        "model": model,
        "total_clips": len(merged_clips),
        "clips": merged_clips,
    }
    if "scene_detection" in existing_manifest:
        merged_manifest["scene_detection"] = existing_manifest["scene_detection"]
    return merged_manifest
