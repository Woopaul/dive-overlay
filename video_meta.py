"""Extract creation time and duration from video files using ffprobe."""

import json
import os
import sys
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

# When running as a PyInstaller bundle, ffprobe is placed next to the executable.
# On Mac .app bundles the shell PATH is not inherited, so also check Homebrew paths.
def _bundled_ffprobe() -> str | None:
    """Return path to ffprobe bundled inside a PyInstaller package, or None."""
    if not hasattr(sys, "_MEIPASS"):
        return None
    name = "ffprobe.exe" if sys.platform == "win32" else "ffprobe"
    path = os.path.join(sys._MEIPASS, name)
    return path if os.path.exists(path) else None


_FFPROBE_CANDIDATES = [
    "ffprobe",                          # already on PATH (script / Windows)
    "/opt/homebrew/bin/ffprobe",        # Homebrew on Apple Silicon
    "/usr/local/bin/ffprobe",           # Homebrew on Intel Mac
    "/usr/bin/ffprobe",                 # system install
]


def _find_ffprobe() -> str:
    bundled = _bundled_ffprobe()
    if bundled:
        return bundled
    for candidate in _FFPROBE_CANDIDATES:
        try:
            result = subprocess.run(
                [candidate, "-version"],
                capture_output=True, timeout=5,
            )
            if result.returncode == 0:
                return candidate
        except (FileNotFoundError, OSError):
            continue
    raise FileNotFoundError(
        "ffprobe를 찾을 수 없습니다.\n"
        "FFmpeg을 설치해주세요: https://ffmpeg.org/download.html\n"
        "Mac: brew install ffmpeg"
    )


_FFPROBE_BIN: str | None = None


def _ffprobe() -> str:
    global _FFPROBE_BIN
    if _FFPROBE_BIN is None:
        _FFPROBE_BIN = _find_ffprobe()
    return _FFPROBE_BIN


def get_video_meta(video_path: str | Path) -> dict:
    """
    Return:
        creation_time (datetime, UTC)  – when recording started
        duration_s (float)             – total length in seconds
    """
    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    cmd = [
        _ffprobe(), "-v", "quiet",
        "-print_format", "json",
        "-show_format", "-show_streams",
        str(video_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")

    info = json.loads(result.stdout)
    fmt = info.get("format", {})
    tags = fmt.get("tags", {})

    creation_time = None
    for key in ("creation_time", "date"):
        raw = tags.get(key) or tags.get(key.lower())
        if raw:
            creation_time = _parse_creation_time(raw)
            break

    if creation_time is None:
        for stream in info.get("streams", []):
            raw = stream.get("tags", {}).get("creation_time")
            if raw:
                creation_time = _parse_creation_time(raw)
                break

    duration_s = float(fmt.get("duration", 0))

    return {
        "creation_time": creation_time,
        "duration_s": duration_s,
    }


def _parse_creation_time(raw: str) -> datetime:
    """Parse various datetime string formats into UTC-aware datetime."""
    raw = raw.strip().rstrip("Z")
    formats = [
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y%m%dT%H%M%S",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse creation_time: {raw!r}")


def infer_station_name(video_path: str | Path) -> str:
    """Use the parent folder name as the station name."""
    return Path(video_path).parent.name
