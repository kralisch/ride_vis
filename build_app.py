#!/usr/bin/env python3
"""Build the web app.

    python build_app.py                  # build into app/
    python build_app.py --serve          # build, serve locally and open
    python build_app.py --full half      # lightbox link at half resolution
    python build_app.py --full none      # no large images at all
    python build_app.py --standalone     # usable by double click, no server

With --standalone a double click on app/index.html is enough. Without it a web
server is needed, because the browser will not let the page read the photo
markers off the file system - that is what --serve is for.
"""

from __future__ import annotations

import argparse
import base64
import functools
import http.server
import shutil
import webbrowser
from pathlib import Path

from ride_vis.config import load_collection_photos, load_config
from ride_vis.export import build_payload, write
from ride_vis.images import FULL_MODES, HALF_DIR, marker, prepare
from ride_vis.match import GPS, OUTSIDE, TRACK, TRACK_GAP, place_photos, verify_offset
from ride_vis.palette import COLLECTION_COLORS
from ride_vis.route import load_track
from ride_vis.ui import load_ui

ROOT = Path(__file__).parent
CONFIG_FILE = ROOT / "ride.toml"
UI_FILE = ROOT / "ui.toml"
LANG_DIR = ROOT / "lang"
WEB_DIR = ROOT / "web"
APP_DIR = ROOT / "app"

RING_PATTERN = {TRACK: "solid", GPS: "solid", TRACK_GAP: "dashed", OUTSIDE: "dotted"}
"""A photo marker's ring shows how certain its position is."""

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


def build_markers(placements, out_dir: Path, colors: dict[str, str]) -> None:
    """Render the round photo marker for every image.

    Ring colour = collection, ring pattern = provenance of the position. The
    riding day is already in the line the marker sits on and would be doubled up.
    """
    marker_dir = out_dir / "markers"
    marker_dir.mkdir(parents=True, exist_ok=True)
    for placement in placements:
        folder = marker_dir / (placement.photo.collection or "photos")
        folder.mkdir(parents=True, exist_ok=True)
        marker(
            placement.photo.path,
            folder / f"{placement.photo.path.stem}.png",
            colors[placement.photo.collection],
            RING_PATTERN[placement.source],
        )


def inline_markers(assets: dict, out_dir: Path) -> None:
    """Move the markers into the tour data as data URIs.

    When the page is opened straight from disk, every file counts as a foreign
    origin. MapLibre has to read a marker's pixels into a canvas, and that is
    what the browser then forbids. As a data URI the restriction falls away -
    displaying them was always allowed, only reading them back was not.
    """
    for entry in assets.values():
        raw = (out_dir / entry["marker"]).read_bytes()
        entry["marker"] = "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def drop_stale(out_dir: Path, photos, full: str) -> None:
    """Remove everything in app/ that no longer has a source.

    Covers whole collections as well as single images. Without it a photo
    deleted from the source would linger in the bundle and be published along
    with the rest.
    """
    kinds = ("thumbs", "photos", "markers", "original", HALF_DIR)
    expected: dict[str, set[str]] = {kind: set() for kind in kinds}
    for photo in photos:
        folder = photo.collection or "photos"
        expected["thumbs"].add(f"{folder}/{photo.path.stem}.jpg")
        expected["photos"].add(f"{folder}/{photo.path.stem}.jpg")
        expected["markers"].add(f"{folder}/{photo.path.stem}.png")
        if full == "original":
            expected["original"].add(f"{folder}/{photo.name}")
        elif full == "half":
            expected[HALF_DIR].add(f"{folder}/{photo.path.stem}.jpg")

    removed, freed = 0, 0
    for kind, wanted in expected.items():
        parent = out_dir / kind
        if not parent.is_dir():
            continue
        for path in sorted(parent.rglob("*")):
            if path.is_file() and f"{path.parent.name}/{path.name}" not in wanted:
                freed += path.stat().st_size
                path.unlink()
                removed += 1
        for folder in sorted(parent.iterdir(), reverse=True):
            if folder.is_dir() and not any(folder.iterdir()):
                folder.rmdir()
        if not any(parent.iterdir()):
            parent.rmdir()
    if removed:
        print(f"        removed {removed} orphaned files ({freed / 1024 ** 2:.0f} MB without a source)")


def serve(directory: Path, port: int = 8000) -> None:
    # Threading rather than the single threaded default: the map asks for about
    # a hundred marker images at once, and serving those in sequence drags.
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    http.server.ThreadingHTTPServer.allow_reuse_address = True
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as httpd:
        url = f"http://127.0.0.1:{port}/"
        print(f"Server  {url}  (Ctrl+C to stop)")
        webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true", help="serve locally and open")
    parser.add_argument(
        "--standalone", action="store_true",
        help="embed the markers in tour.js so index.html works by double click",
    )
    parser.add_argument(
        "--full", choices=FULL_MODES, default="original",
        help="what sits behind the lightbox link: the untouched camera file "
             "(original), a version at half the edge length (half), or nothing (none)",
    )
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    config = load_config(CONFIG_FILE, ROOT)
    tour, collections = config.tour, config.collections

    ui, untranslated = load_ui(UI_FILE, LANG_DIR)
    if untranslated:
        print(f"Language {ui.language}: {len(untranslated)} keys fall back to English ({', '.join(untranslated[:5])})")

    track = load_track(tour.track, labels=stage_labels(tour.stages))
    if not tour.stages:
        template = ui.strings.get("dayLabel", "Day {n}")
        for day in track.days:
            day.label = template.replace("{n}", str(day.index))
    photos = []
    print(f"Track   {track.distance_m / 1000:7.1f} km, {len(track.days)} riding days")
    width = max(len(c.name) for c in collections)
    for collection in collections:
        found = load_collection_photos(collection)
        photos.extend(found)
        with_gps = sum(1 for p in found if p.gps)
        minutes = collection.clock_offset.total_seconds() / 60
        print(
            f"Set     {collection.name:<{width}}  {collection.color}  "
            f"{len(found):4d} photos, {with_gps:3d} with GPS"
            + (f", clock {minutes:+.0f} min" if minutes else "")
        )
    photos.sort(key=lambda p: p.taken)
    placements = place_photos(photos, track)

    checks = sorted(metres for _, metres in verify_offset(photos, track))
    if checks:
        middle = checks[len(checks) // 2]
        print(
            f"Check   {len(checks)} photos with GPS: distance to the track position "
            f"is {middle:.0f} m in the middle, {checks[-1]:.0f} m at worst"
        )

    counts: dict[str, int] = {}
    for placement in placements:
        counts[placement.source] = counts.get(placement.source, 0) + 1
    for source, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"        {count:4d} {SOURCE_LABELS[source]}")

    if len(collections) > len(COLLECTION_COLORS):
        extra = ", ".join(c.name for c in collections[len(COLLECTION_COLORS):])
        print(f"Note    grey for want of a checked colour: {extra}")
        print("        the checked palette covers three collections; give further")
        print('        ones color = "#..." in the configuration')

    APP_DIR.mkdir(exist_ok=True)
    for name in ("index.html", "app.css", "app.js"):
        shutil.copy2(WEB_DIR / name, APP_DIR / name)
    shutil.copytree(WEB_DIR / "vendor", APP_DIR / "vendor", dirs_exist_ok=True)
    # GitHub Pages would otherwise run the folder through Jekyll.
    (APP_DIR / ".nojekyll").touch()

    print("Images  scaling previews, views and markers ...")
    assets = prepare(photos, APP_DIR, full=args.full)
    if args.full != "none":
        total = sum(entry["fullBytes"] for entry in assets.values())
        how = "copied untouched" if args.full == "original" else "scaled to half the edge length"
        print(f"        lightbox link {how}: {total / 1024 ** 3:.2f} GB")

    colors = {c.id: c.color for c in collections}
    build_markers(placements, APP_DIR, colors)
    for placement in placements:
        folder = placement.photo.collection or "photos"
        assets[placement.photo.key]["marker"] = f"markers/{folder}/{placement.photo.path.stem}.png"
    if args.standalone:
        inline_markers(assets, APP_DIR)

    drop_stale(APP_DIR, photos, args.full)

    payload = build_payload(tour, track, placements, assets, collections, ui, args.full)
    size = write(payload, APP_DIR)
    print(f"Data    tour.js {size / 1024 ** 2:.1f} MB (tour.json alongside)")
    if args.standalone:
        print("        markers embedded - index.html works by double click")
    else:
        print("        for double click use: --standalone")
    print(f"App     {APP_DIR}")

    if args.serve:
        serve(APP_DIR, args.port)


if __name__ == "__main__":
    main()
