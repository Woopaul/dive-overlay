"""Generate SRT subtitle file from dive data matched to video timestamps."""

from datetime import datetime, timedelta, timezone
from pathlib import Path


def _srt_time(seconds: float) -> str:
    """Convert float seconds to SRT timestamp format HH:MM:SS,mmm."""
    total_ms = int(seconds * 1000)
    h = total_ms // 3_600_000
    m = (total_ms % 3_600_000) // 60_000
    s = (total_ms % 60_000) // 1_000
    ms = total_ms % 1_000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def generate_srt(
    output_path: str | Path,
    station: str,
    video_start: datetime,
    duration_s: float,
    dive_lookup: dict,
    utc_offset_hours: float = 9.0,
    interval_s: int = 1,
    time_shift_s: float = 0.0,
) -> Path:
    """
    Write an SRT file where each subtitle covers `interval_s` seconds and shows:
        [station]  YYYY-MM-DD HH:MM:SS (local time)
        Depth: X.Xm  |  Temp: X.X°C

    Args:
        dive_lookup: dict keyed by UTC datetime from fit_parser.build_lookup()
        utc_offset_hours: local timezone offset (default 9 = KST)
        interval_s: subtitle display interval in seconds
        time_shift_s: camera clock offset in seconds relative to dive computer.
                      Positive = camera was ahead (e.g. +30 means camera showed
                      30s more than the dive computer at the same moment).
                      Applied to BOTH the displayed time and the FIT data lookup.
    """
    output_path = Path(output_path)
    local_offset = timedelta(hours=utc_offset_hours)
    correction = timedelta(seconds=time_shift_s)

    entries = []
    total_steps = int(duration_s // interval_s)

    for i in range(total_steps):
        t_start = i * interval_s
        t_end = t_start + interval_s

        # Correct camera clock error: shift both display time and FIT lookup key
        current_utc = (video_start + timedelta(seconds=t_start) - correction).replace(microsecond=0)

        local_dt = current_utc + local_offset
        dt_str = local_dt.strftime("%Y-%m-%d %H:%M:%S")

        record = dive_lookup.get(current_utc)
        if record:
            depth_str = f"{record['depth_m']:.1f} m"
            temp_val = record["temp_c"]
            temp_str = f"{temp_val:.1f} °C" if temp_val is not None else "N/A"
        else:
            depth_str = "-- m"
            temp_str = "-- °C"

        text = f"[{station}]  {dt_str}\nDepth: {depth_str}  |  Temp: {temp_str}"

        entries.append(
            f"{i + 1}\n"
            f"{_srt_time(t_start)} --> {_srt_time(t_end)}\n"
            f"{text}\n"
        )

    output_path.write_text("\n".join(entries), encoding="utf-8")
    return output_path
