from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import get_video_metadata, save_json, timestamp_utc


def write_clip_analysis(clip_path: Path, output_path: Path, clip_id: str) -> dict[str, Any]:
    metadata = get_video_metadata(clip_path)
    analysis = {
        "clip_id": clip_id,
        "generated_at": timestamp_utc(),
        "technical_metadata": metadata,
        "semantic_analysis": {
            "lighting": "unknown",
            "camera_angle": "unknown",
            "camera_type": "unknown",
            "action": "Semantic clip analysis is not implemented yet.",
        },
        "notes": [
            "This file is a placeholder for the future AI-powered clip analysis step.",
            "It currently records technical metadata so downstream steps have a stable contract.",
        ],
    }
    save_json(output_path, analysis)
    return analysis

