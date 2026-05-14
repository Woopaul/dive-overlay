"""Parse Garmin .fit dive files and return time-series depth/temperature data."""

from datetime import datetime, timezone
from pathlib import Path

try:
    import fitparse
except ImportError:
    raise ImportError("fitparse is required: pip install fitparse")


def parse_fit_dive(fit_path: str | Path) -> list[dict]:
    """
    Parse a Garmin .fit file and return a list of records with:
        timestamp (datetime, UTC), depth_m (float), temp_c (float)

    Garmin Descent stores per-second dive samples in 'record' messages.
    Temperature is stored in Celsius (some firmwares store in Kelvin — handled below).
    """
    fit_path = Path(fit_path)
    if not fit_path.exists():
        raise FileNotFoundError(f"FIT file not found: {fit_path}")

    fitfile = fitparse.FitFile(str(fit_path))
    records = []

    for msg in fitfile.get_messages("record"):
        data = {f.name: f.value for f in msg}

        ts = data.get("timestamp")
        depth = data.get("depth")
        temp = data.get("temperature")

        if ts is None or depth is None:
            continue

        if isinstance(ts, datetime) and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        if temp is not None and temp > 100:
            temp = temp - 273.15

        records.append({
            "timestamp": ts,
            "depth_m": round(float(depth), 2),
            "temp_c": round(float(temp), 1) if temp is not None else None,
        })

    records.sort(key=lambda r: r["timestamp"])
    return records


def build_lookup(records: list[dict]) -> dict[datetime, dict]:
    """Build a timestamp -> record dict for O(1) lookup."""
    return {r["timestamp"]: r for r in records}


def parse_dive_file(path: str | Path) -> list[dict]:
    """
    Auto-detect file format (.fit, .uddf, or .csv) and return dive records.
    Returns a list of dicts: timestamp (UTC datetime), depth_m, temp_c.

    For CSV files, raises CsvConfigRequired so the caller can collect
    column mapping + dive_start from the user before retrying with
    parse_csv_with_config().
    """
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix == ".fit":
        return parse_fit_dive(path)
    elif suffix in (".uddf", ".xml"):
        from uddf_parser import parse_uddf_dive
        return parse_uddf_dive(path)
    elif suffix == ".csv":
        from csv_parser import detect_columns, CsvConfigRequired
        raise CsvConfigRequired(detect_columns(path))
    else:
        raise ValueError(f"Unsupported dive file format: {suffix!r}  (expected .fit, .uddf, or .csv)")


def parse_csv_with_config(path: str | Path, cfg: dict) -> list[dict]:
    """Parse a CSV file using a config dict produced by the CSV mapping dialog."""
    from csv_parser import parse_csv_dive
    return parse_csv_dive(
        path,
        time_col=cfg["time_col"],
        depth_col=cfg["depth_col"],
        temp_col=cfg.get("temp_col"),
        time_mode=cfg["time_mode"],
        dive_start=cfg.get("dive_start"),
    )
