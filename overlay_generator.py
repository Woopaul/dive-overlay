#!/usr/bin/env python3
"""
Generate SRT subtitle files for underwater videos using Garmin dive computer data.

Usage:
    python overlay_generator.py VIDEO_FILE FIT_FILE [options]

Example:
    python overlay_generator.py dokdo_hokdomgul/GX010123.MP4 dive.fit
    python overlay_generator.py dokdo_hokdomgul/GX010123.MP4 dive.fit --station "독도(혹돔굴)" --offset 9
"""

import argparse
import sys
from pathlib import Path

from fit_parser import parse_fit_dive, build_lookup
from video_meta import get_video_meta, infer_station_name
from srt_generator import generate_srt


def main():
    parser = argparse.ArgumentParser(
        description="Generate SRT subtitles for underwater videos with dive computer data."
    )
    parser.add_argument("video", help="Path to the video file")
    parser.add_argument("fit", help="Path to the Garmin .fit file")
    parser.add_argument(
        "--station", "-s",
        help="Station name (default: parent folder name of video)",
        default=None,
    )
    parser.add_argument(
        "--offset", "-o",
        help="UTC offset in hours for local time display (default: 9 for KST)",
        type=float,
        default=9.0,
    )
    parser.add_argument(
        "--output",
        help="Output SRT file path (default: same location as video with .srt extension)",
        default=None,
    )
    parser.add_argument(
        "--time-shift",
        help="Manually shift dive data timestamps by N seconds (positive = forward)",
        type=float,
        default=0.0,
        dest="time_shift",
    )
    args = parser.parse_args()

    video_path = Path(args.video)
    fit_path = Path(args.fit)

    print(f"Video  : {video_path}")
    print(f"FIT    : {fit_path}")

    print("Extracting video metadata...")
    meta = get_video_meta(video_path)

    if meta["creation_time"] is None:
        print("ERROR: Could not extract creation_time from video metadata.")
        print("       The video file may not have embedded timestamp information.")
        print("       Try re-encoding with a camera that embeds timestamps, or use --time-shift.")
        sys.exit(1)

    print(f"  Start time (UTC): {meta['creation_time']}")
    print(f"  Duration        : {meta['duration_s']:.1f}s ({meta['duration_s']/60:.1f} min)")

    print("Parsing FIT file...")
    records = parse_fit_dive(fit_path)
    if not records:
        print("ERROR: No dive records found in FIT file.")
        sys.exit(1)

    if args.time_shift != 0:
        from datetime import timedelta
        records = [
            {**r, "timestamp": r["timestamp"] + timedelta(seconds=args.time_shift)}
            for r in records
        ]

    print(f"  Dive records    : {len(records)}")
    print(f"  Dive start (UTC): {records[0]['timestamp']}")
    print(f"  Dive end   (UTC): {records[-1]['timestamp']}")
    print(f"  Depth range     : {min(r['depth_m'] for r in records):.1f} – {max(r['depth_m'] for r in records):.1f} m")

    lookup = build_lookup(records)

    station = args.station or infer_station_name(video_path)
    print(f"  Station name    : {station}")

    if args.output:
        output_path = Path(args.output)
    else:
        output_path = video_path.with_suffix(".srt")

    print(f"Generating SRT → {output_path}")
    generate_srt(
        output_path=output_path,
        station=station,
        video_start=meta["creation_time"],
        duration_s=meta["duration_s"],
        dive_lookup=lookup,
        utc_offset_hours=args.offset,
    )

    matched = sum(
        1 for i in range(int(meta["duration_s"]))
        if (meta["creation_time"].replace(microsecond=0)
            + __import__("datetime").timedelta(seconds=i)) in lookup
    )
    total = int(meta["duration_s"])
    print(f"Done. Matched {matched}/{total} seconds with dive data.")
    if matched < total * 0.5:
        print("WARNING: Less than 50% of video frames matched dive data.")
        print("         Check that the video and FIT file are from the same dive.")
        print("         Use --time-shift to adjust if timestamps are misaligned.")


if __name__ == "__main__":
    main()
