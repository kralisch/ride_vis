#!/usr/bin/env python3
"""Build the plain Leaflet map: track, riding days and photos.

    python build_map.py [--open]

Unlike the web app this one needs no server - open out/map.html directly.
"""

from __future__ import annotations

import argparse
import webbrowser
from pathlib import Path

from ride_vis.config import load_collection_photos, load_config
from ride_vis.images import prepare
from ride_vis.match import GPS, OUTSIDE, TRACK, TRACK_GAP, place_photos, verify_offset
from ride_vis.render import build_map
from ride_vis.route import load_track
from ride_vis.ui import load_ui

ROOT = Path(__file__).parent
CONFIG_FILE = ROOT / "ride.toml"
UI_FILE = ROOT / "ui.toml"
LANG_DIR = ROOT / "lang"
OUT_DIR = ROOT / "out"

SOURCE_LABELS = {
    GPS: "GPS in the photo",
    TRACK: "interpolated from capture time",
    TRACK_GAP: "interpolated across a recording gap",
    OUTSIDE: "outside the recording",
}


def stage_labels(directory: Path | None) -> list[str]:
    """Day names taken from the planned stage files, if any are configured."""
    if directory is None:
        return []
    labels = []
    for path in sorted(directory.glob("[0-9]_*.gpx")):
        parts = path.stem.split("_")
        labels.append(" ".join(parts[1:]).replace("-", " - "))
    return labels


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--open", action="store_true", help="open the map in a browser")
    args = parser.parse_args()

    try:
        config = load_config(CONFIG_FILE, ROOT)
    except (ValueError, OSError) as broken:
        raise SystemExit(f"Config  {broken}") from None
    tour, collections = config.tour, config.collections

    ui, _ = load_ui(UI_FILE, LANG_DIR)
    try:
        track = load_track(tour.track, labels=stage_labels(tour.stages))
    except (ValueError, OSError) as broken:
        raise SystemExit(f"Track   {broken}") from None
    if not tour.stages:
        template = ui.strings.get("dayLabel", "Day {n}")
        for day in track.days:
            day.label = template.replace("{n}", str(day.index))
    photos = [photo for c in collections for photo in load_collection_photos(c)]
    photos.sort(key=lambda p: p.taken)
    files = f", {len(tour.track)} files" if len(tour.track) > 1 else ""
    print(f"Track   {track.distance_m / 1000:7.1f} km, {len(track.days)} riding days{files}")
    print(f"Photos  {len(photos)} with a capture time, {sum(1 for p in photos if p.gps)} with GPS")

    checks = sorted(metres for _, metres in verify_offset(photos, track))
    if checks:
        middle = checks[len(checks) // 2]
        print(
            f"Check   {len(checks)} photos with GPS: distance to the track position "
            f"is {middle:.0f} m in the middle, {checks[-1]:.0f} m at worst"
        )

    placements = place_photos(photos, track)
    counts: dict[str, int] = {}
    for placement in placements:
        counts[placement.source] = counts.get(placement.source, 0) + 1
    for source, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"        {count:4d} {SOURCE_LABELS[source]}")

    print("Images  scaling previews and views ...")
    assets = prepare(photos, OUT_DIR, full="none")

    out = OUT_DIR / "map.html"
    build_map(track, placements, assets, collections, tour.title, ui).save(str(out))
    print(f"Map     {out}")
    if args.open:
        webbrowser.open(out.as_uri())


if __name__ == "__main__":
    main()
