"""Parse UDDF (Universal Dive Data Format) XML files and return time-series depth/temperature data."""

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _strip_ns(tag: str) -> str:
    return re.sub(r"\{[^}]*\}", "", tag)


def _find(el: ET.Element, tag: str) -> ET.Element | None:
    for child in el:
        if _strip_ns(child.tag) == tag:
            return child
    return None


def _findall(el: ET.Element, tag: str) -> list[ET.Element]:
    return [child for child in el if _strip_ns(child.tag) == tag]


def _iter_tag(root: ET.Element, tag: str):
    for el in root.iter():
        if _strip_ns(el.tag) == tag:
            yield el


# Matches ISO 8601 offsets like +09:00, -05:30, +00:09 (Oceanic+ bug)
_TZ_PATTERN = re.compile(r"([+-])(\d{2}):(\d{2})$")


def _parse_datetime(raw: str) -> datetime:
    """
    Parse UDDF datetime string to UTC-aware datetime.

    Handles the Oceanic+ app bug where KST (+09:00) is written as +00:09
    (hours and minutes swapped). Detection: if the offset is +00:HH where
    HH is a plausible hour (01–14), swap to treat it as +HH:00.
    """
    raw = raw.strip()

    m = _TZ_PATTERN.search(raw)
    if m:
        sign, hh, mm = m.group(1), int(m.group(2)), int(m.group(3))
        # Oceanic+ bug: +00:09 means +09:00 (hours written as minutes)
        if hh == 0 and 1 <= mm <= 14:
            hh, mm = mm, 0
        offset = timedelta(hours=hh, minutes=mm)
        if sign == "-":
            offset = -offset
        base_str = raw[: m.start()]
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.strptime(base_str, fmt)
                return (dt - offset).replace(tzinfo=timezone.utc)
            except ValueError:
                continue

    # No timezone suffix — assume UTC
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(raw.rstrip("Z"), fmt.rstrip("Z"))
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    raise ValueError(f"Cannot parse UDDF datetime: {raw!r}")


def parse_uddf_dive(uddf_path: str | Path) -> list[dict]:
    """
    Parse a UDDF file and return 1-Hz time-series records:
        timestamp (datetime, UTC), depth_m (float), temp_c (float | None)

    Waypoints with intervals > 1 s are linearly interpolated to fill every
    second (e.g. Apple Watch records every 15 s; Garmin records every 1 s).
    If multiple dives are present, all are merged and sorted by time.
    """
    uddf_path = Path(uddf_path)
    if not uddf_path.exists():
        raise FileNotFoundError(f"UDDF file not found: {uddf_path}")

    tree = ET.parse(str(uddf_path))
    root = tree.getroot()

    all_records = []

    for dive in _iter_tag(root, "dive"):
        dive_start = _get_dive_start(dive)
        if dive_start is None:
            continue

        samples = _find(dive, "samples")
        if samples is None:
            continue

        raw = []
        for wp in _findall(samples, "waypoint"):
            divetime_el = _find(wp, "divetime")
            depth_el = _find(wp, "depth")
            temp_el = _find(wp, "temperature")

            if divetime_el is None or depth_el is None:
                continue
            try:
                divetime_s = float(divetime_el.text)
                depth_m = float(depth_el.text)
            except (TypeError, ValueError):
                continue

            temp_c = None
            if temp_el is not None and temp_el.text:
                try:
                    temp_c = round(float(temp_el.text) - 273.15, 1)
                except ValueError:
                    pass

            ts = (dive_start + timedelta(seconds=divetime_s)).replace(microsecond=0)
            raw.append({"timestamp": ts, "depth_m": round(depth_m, 2), "temp_c": temp_c})

        all_records.extend(_interpolate_1hz(raw))

    all_records.sort(key=lambda r: r["timestamp"])
    return all_records


def _interpolate_1hz(records: list[dict]) -> list[dict]:
    """
    Linearly interpolate sparse waypoints to 1-Hz (one record per second).
    If the source is already 1 Hz the input is returned as-is.
    """
    if len(records) < 2:
        return records

    out = []
    for i in range(len(records) - 1):
        r0, r1 = records[i], records[i + 1]
        gap = int((r1["timestamp"] - r0["timestamp"]).total_seconds())

        if gap <= 1:
            out.append(r0)
            continue

        for s in range(gap):
            frac = s / gap
            depth = r0["depth_m"] + (r1["depth_m"] - r0["depth_m"]) * frac
            if r0["temp_c"] is not None and r1["temp_c"] is not None:
                temp = round(r0["temp_c"] + (r1["temp_c"] - r0["temp_c"]) * frac, 1)
            else:
                temp = r0["temp_c"] if r0["temp_c"] is not None else r1["temp_c"]
            out.append({
                "timestamp": r0["timestamp"] + timedelta(seconds=s),
                "depth_m": round(depth, 2),
                "temp_c": temp,
            })

    out.append(records[-1])
    return out


def _get_dive_start(dive: ET.Element) -> datetime | None:
    info = _find(dive, "informationbeforedive")
    if info is None:
        return None
    for tag in ("datetime", "date"):
        el = _find(info, tag)
        if el is not None and el.text:
            try:
                return _parse_datetime(el.text)
            except ValueError:
                pass
    return None
