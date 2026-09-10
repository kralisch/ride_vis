"""Write the tour data for the web app."""

from __future__ import annotations

import json
from pathlib import Path

from .config import Collection, Tour
from .match import Placement
from .palette import DASH_ARRAYS, day_style, direction
from .route import Day, Track
from .ui import Ui

COORD_DIGITS = 5
"""About 1 m of resolution - enough for hairpins, keeps the payload small."""


def _local(when, offset) -> str:
    """Track times are UTC; what gets shown is the local time of the ride."""
    return (when + offset).strftime("%H:%M")


def _day_coords(day: Day) -> list[list[float]]:
    """Per point [lon, lat, elevation, seconds from day start, metres from day start]."""
    start = day.start
    return [
        [
            round(point.lon, COORD_DIGITS),
            round(point.lat, COORD_DIGITS),
            round(point.ele) if point.ele is not None else None,
            int((point.time - start).total_seconds()),
            round(distance),
        ]
        for point, distance in zip(day.points, day.cum)
    ]


def _day_entry(day: Day, offset) -> dict:
    color, dash = day_style(day.index)
    elevations = [p.ele for p in day.points if p.ele is not None]
    return {
        "index": day.index,
        "label": day.label,
        "date": day.date.isoformat(),
        "direction": direction(day.index),
        "color": color,
        "dash": dash,
        "dashArray": DASH_ARRAYS[dash],
        "start": _local(day.start, offset),
        "end": _local(day.end, offset),
        "distance_m": round(day.distance_m),
        "duration_s": int(day.duration.total_seconds()),
        "ascent_m": round(day.ascent_m),
        "ele_min": min(elevations) if elevations else None,
        "ele_max": max(elevations) if elevations else None,
        "coords": _day_coords(day),
    }


def _photo_entry(placement: Placement, assets: dict) -> dict:
    photo = placement.photo
    files = assets[photo.key]
    return {
        "name": photo.name,
        "key": photo.key,
        "collection": photo.collection,
        "day": placement.day.index,
        "time": photo.taken.strftime("%H:%M"),
        "datetime": photo.taken.isoformat(timespec="seconds"),
        "t": int((placement.utc - placement.day.start).total_seconds()),
        "d": round(placement.distance_m),
        "lon": round(placement.position[1], COORD_DIGITS),
        "lat": round(placement.position[0], COORD_DIGITS),
        "ele": round(placement.elevation) if placement.elevation is not None else None,
        "source": placement.source,
        **files,
    }


def _collection_entry(collection: Collection, placements: list[Placement]) -> dict:
    return {
        "id": collection.id,
        "name": collection.name,
        "color": collection.color,
        "enabled": collection.enabled,
        "photos": sum(1 for p in placements if p.photo.collection == collection.id),
    }


def build_payload(
    tour: Tour,
    track: Track,
    placements: list[Placement],
    assets: dict,
    collections: list[Collection],
    ui: Ui,
    full: str = "original",
) -> dict:
    lats = [p.lat for p in track.points]
    lons = [p.lon for p in track.points]
    return {
        "title": tour.title,
        "fullKind": full,
        "ui": {
            "language": ui.language,
            "locale": ui.locale,
            "basemap": ui.basemap,
            "terrain": ui.terrain,
            "exaggeration": ui.exaggeration,
            "strings": ui.strings,
            "basemaps": ui.basemap_names,
        },
        "bounds": [min(lons), min(lats), max(lons), max(lats)],
        "totals": {
            "distance_m": round(track.distance_m),
            "ascent_m": round(sum(day.ascent_m for day in track.days)),
            "duration_s": int(sum(day.duration.total_seconds() for day in track.days)),
            "days": len(track.days),
            "photos": len(placements),
        },
        "collections": [_collection_entry(c, placements) for c in collections],
        "days": [_day_entry(day, tour.utc_offset) for day in track.days],
        "photos": [_photo_entry(p, assets) for p in placements],
    }


def write(payload: dict, directory: Path) -> int:
    """Store the tour data and return its size in bytes.

    The page loads `tour.js` as a script, so it also works without a web server.
    `tour.json` sits next to it unchanged, for anything else that wants the data.
    """
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    (directory / "tour.json").write_text(body, encoding="utf-8")
    script = directory / "tour.js"
    script.write_text(f"window.TOUR={body};\n", encoding="utf-8")
    return script.stat().st_size
