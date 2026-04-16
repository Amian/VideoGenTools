from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import RUNS_DIR, ensure_dir, load_json, save_json, timestamp_utc


RUN_SUBDIRECTORIES = (
    "input",
    "clips",
    "frames",
    "modified_frames",
    "prompts",
    "animations",
    "output",
    "logs",
    "manifests",
)


def get_run_dir(run_id: str) -> Path:
    return RUNS_DIR / run_id


def get_run_manifest_path(run_id: str) -> Path:
    return get_run_dir(run_id) / "manifests" / "run.json"


def get_clips_manifest_path(run_id: str) -> Path:
    return get_run_dir(run_id) / "manifests" / "clips.json"


def get_clip_dir(run_id: str, clip_id: str) -> Path:
    return get_run_dir(run_id) / "clips" / clip_id


def create_run_directories(run_id: str) -> Path:
    run_dir = get_run_dir(run_id)
    ensure_dir(run_dir)
    for name in RUN_SUBDIRECTORIES:
        ensure_dir(run_dir / name)
    return run_dir


def initialize_run_manifest(run_id: str, source_video: str, run_name: str | None) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "run_name": run_name or run_id,
        "created_at": timestamp_utc(),
        "updated_at": timestamp_utc(),
        "status": "initialized",
        "source_video": source_video,
        "input_video": None,
        "input_metadata": None,
        "steps": {
            "setup_run": {
                "status": "completed",
                "updated_at": timestamp_utc(),
            }
        },
    }


def load_run_manifest(run_id: str) -> dict[str, Any]:
    manifest_path = get_run_manifest_path(run_id)
    manifest = load_json(manifest_path)
    if manifest is None:
        raise FileNotFoundError(f"Run manifest not found: {manifest_path}")
    return manifest


def save_run_manifest(run_id: str, manifest: dict[str, Any]) -> None:
    manifest["updated_at"] = timestamp_utc()
    save_json(get_run_manifest_path(run_id), manifest)


def mark_run_step(run_id: str, step_name: str, status: str) -> dict[str, Any]:
    manifest = load_run_manifest(run_id)
    manifest.setdefault("steps", {})
    manifest["steps"][step_name] = {
        "status": status,
        "updated_at": timestamp_utc(),
    }
    save_run_manifest(run_id, manifest)
    return manifest


def initialize_clips_manifest(run_id: str) -> dict[str, Any]:
    manifest = {
        "run_id": run_id,
        "created_at": timestamp_utc(),
        "updated_at": timestamp_utc(),
        "scene_detection": None,
        "clips": [],
    }
    save_clips_manifest(run_id, manifest)
    return manifest


def load_clips_manifest(run_id: str) -> dict[str, Any]:
    manifest_path = get_clips_manifest_path(run_id)
    manifest = load_json(manifest_path)
    if manifest is None:
        raise FileNotFoundError(f"Clips manifest not found: {manifest_path}")
    return manifest


def save_clips_manifest(run_id: str, manifest: dict[str, Any]) -> None:
    manifest["updated_at"] = timestamp_utc()
    save_json(get_clips_manifest_path(run_id), manifest)


def find_clip_entry(run_id: str, clip_id: str) -> dict[str, Any]:
    clips_manifest = load_clips_manifest(run_id)
    for clip in clips_manifest.get("clips", []):
        if clip.get("clip_id") == clip_id:
            return clip
    raise KeyError(f"Clip {clip_id} was not found in run {run_id}")


def update_clip_entry(run_id: str, clip_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    clips_manifest = load_clips_manifest(run_id)
    for clip in clips_manifest.get("clips", []):
        if clip.get("clip_id") == clip_id:
            clip.update(updates)
            save_clips_manifest(run_id, clips_manifest)
            return clip
    raise KeyError(f"Clip {clip_id} was not found in run {run_id}")

