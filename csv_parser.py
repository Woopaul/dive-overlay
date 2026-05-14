"""Parse dive computer CSV exports and return time-series depth/temperature data."""


class CsvConfigRequired(Exception):
    """Raised when a CSV file needs column mapping before it can be parsed.
    The exception carries the auto-detected mapping dict from detect_columns()."""
    def __init__(self, detected: dict):
        super().__init__("CSV column mapping required")
        self.detected = detected

import csv
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Common column name patterns (lowercase, stripped)
_TIME_KEYWORDS = [
    "timestamp", "datetime", "date/time", "date time", "utc", "time",
    "elapsed time", "elapsed time (s)", "elapsed", "divetime", "dive time",
    "sample time", "zeit", "temps",
]
_DEPTH_KEYWORDS = [
    "depth", "depth(m)", "depth (m)", "depth_m", "tiefe", "profundidad",
    "profondeur", "수심",
]
_TEMP_KEYWORDS = [
    "temperature", "temp", "temperature(°c)", "temperature (°c)", "temp(c)",
    "temp (c)", "water temp", "water temperature", "wassertemp", "wassert",
    "température", "수온",
]

# Datetime string formats tried in order
_DT_FORMATS = [
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
    "%d/%m/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M:%S",
    "%Y-%m-%d",
]


def _norm(s: str) -> str:
    return s.lower().strip()


def detect_columns(path: str | Path) -> dict:
    """
    Read CSV header and return best-guess column mapping:
        {
            "headers": [...],
            "time":  column_name or None,
            "depth": column_name or None,
            "temp":  column_name or None,
            "time_mode": "absolute" | "relative" | "unknown",
        }
    """
    path = Path(path)
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        reader = csv.reader(f)
        # Skip comment/metadata lines at the top
        headers = None
        first_data = None
        for row in reader:
            if not row or all(c.strip() == "" for c in row):
                continue
            if headers is None:
                # Check if this looks like a header row (mostly non-numeric)
                non_numeric = sum(1 for c in row if not _is_numeric(c.strip()))
                if non_numeric >= len(row) // 2:
                    headers = row
                    continue
            if headers is not None and first_data is None:
                first_data = row
                break

    if headers is None:
        return {"headers": [], "time": None, "depth": None, "temp": None, "time_mode": "unknown"}

    headers = [h.strip() for h in headers]
    mapping = {"headers": headers, "time": None, "depth": None, "temp": None}

    for h in headers:
        n = _norm(h)
        if mapping["time"] is None and any(k in n for k in _TIME_KEYWORDS):
            mapping["time"] = h
        elif mapping["depth"] is None and any(k in n for k in _DEPTH_KEYWORDS):
            mapping["depth"] = h
        elif mapping["temp"] is None and any(k in n for k in _TEMP_KEYWORDS):
            mapping["temp"] = h

    # Determine time mode from first data row
    mode = "unknown"
    if mapping["time"] and first_data:
        try:
            idx = headers.index(mapping["time"])
            val = first_data[idx].strip()
            if _is_numeric(val):
                mode = "relative"
            else:
                _parse_dt(val)
                mode = "absolute"
        except (ValueError, IndexError):
            mode = "unknown"

    mapping["time_mode"] = mode
    return mapping


def parse_csv_dive(
    path: str | Path,
    time_col: str,
    depth_col: str,
    temp_col: str | None,
    time_mode: str,
    dive_start: datetime | None = None,
) -> list[dict]:
    """
    Parse a CSV dive file given explicit column assignments.

    Args:
        time_col:   column name for time (absolute datetime string or relative seconds)
        depth_col:  column name for depth in metres
        temp_col:   column name for temperature in °C (None = not available)
        time_mode:  "absolute" | "relative"
        dive_start: required when time_mode == "relative"; UTC datetime of dive start
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {path}")
    if time_mode == "relative" and dive_start is None:
        raise ValueError("dive_start is required when time_mode is 'relative'")

    records = []
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        reader = csv.DictReader(f)
        # Normalise header keys (strip whitespace)
        for raw_row in reader:
            row = {k.strip(): v.strip() for k, v in raw_row.items() if k}

            depth_raw = row.get(depth_col, "").strip()
            if not depth_raw or not _is_numeric(depth_raw):
                continue

            try:
                depth_m = float(depth_raw)
            except ValueError:
                continue

            time_raw = row.get(time_col, "").strip()
            if not time_raw:
                continue

            try:
                if time_mode == "absolute":
                    ts = _parse_dt(time_raw)
                else:
                    ts = dive_start + timedelta(seconds=float(time_raw))
                    ts = ts.replace(microsecond=0)
            except (ValueError, TypeError):
                continue

            temp_c = None
            if temp_col:
                temp_raw = row.get(temp_col, "").strip()
                if temp_raw and _is_numeric(temp_raw):
                    temp_c = round(float(temp_raw), 1)

            records.append({
                "timestamp": ts,
                "depth_m": round(depth_m, 2),
                "temp_c": temp_c,
            })

    records.sort(key=lambda r: r["timestamp"])
    return records


def _is_numeric(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def _parse_dt(s: str) -> datetime:
    s = s.strip().rstrip("Z")
    for fmt in _DT_FORMATS:
        try:
            dt = datetime.strptime(s, fmt.rstrip("Z"))
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse datetime: {s!r}")
