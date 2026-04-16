from __future__ import annotations

import json
import os
import shlex
import subprocess
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any, Sequence


ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
RUNS_DIR = DATA_DIR / "runs"


def load_env_file(path: Path, *, override: bool = False) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue

        if value and len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]

        if override or key not in os.environ:
            os.environ[key] = value


def load_local_env() -> None:
    load_env_file(ROOT_DIR / ".env")
    load_env_file(ROOT_DIR / ".env.local")


load_local_env()


def timestamp_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path: Path, payload: Any) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=False)
        handle.write("\n")


def run_command(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        list(args),
        cwd=str(cwd) if cwd else None,
        check=False,
        text=True,
        capture_output=capture_output,
    )
    if completed.returncode != 0:
        command_text = shlex.join(args)
        stderr = (completed.stderr or "").strip()
        stdout = (completed.stdout or "").strip()
        detail = stderr or stdout or f"exit code {completed.returncode}"
        raise RuntimeError(f"Command failed: {command_text}\n{detail}")
    return completed


def ffprobe_json(video_path: Path) -> dict[str, Any]:
    result = run_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(video_path),
        ],
        capture_output=True,
    )
    return json.loads(result.stdout)


def fraction_to_float(value: str | None) -> float | None:
    if not value or value == "0/0":
        return None
    try:
        return float(Fraction(value))
    except (ValueError, ZeroDivisionError):
        return None


def safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def get_video_metadata(video_path: Path) -> dict[str, Any]:
    probe = ffprobe_json(video_path)
    format_info = probe.get("format", {})
    streams = probe.get("streams", [])
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
    audio_stream = next((stream for stream in streams if stream.get("codec_type") == "audio"), {})

    duration = safe_float(format_info.get("duration")) or safe_float(video_stream.get("duration")) or 0.0
    fps = fraction_to_float(video_stream.get("avg_frame_rate")) or fraction_to_float(video_stream.get("r_frame_rate"))

    return {
        "duration_seconds": duration,
        "size_bytes": safe_float(format_info.get("size")),
        "format_name": format_info.get("format_name"),
        "bit_rate": safe_float(format_info.get("bit_rate")),
        "video": {
            "codec_name": video_stream.get("codec_name"),
            "width": video_stream.get("width"),
            "height": video_stream.get("height"),
            "pix_fmt": video_stream.get("pix_fmt"),
            "fps": fps,
        },
        "audio": {
            "codec_name": audio_stream.get("codec_name"),
            "sample_rate": audio_stream.get("sample_rate"),
            "channels": audio_stream.get("channels"),
        }
        if audio_stream
        else None,
    }
