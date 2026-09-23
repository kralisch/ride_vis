"""Read the project configuration: the tour itself and its photo collections."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from .palette import collection_color
from .photos import Photo, load_photos

DEFAULT_UTC_OFFSET_HOURS = 0
"""Camera clocks are local time. Set the tour's offset if the ride was not in UTC."""

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class Collection:
    id: str
    """Short form used in file paths and deep links."""
    name: str
    location: Path
    enabled: bool = True
    """Whether the collection starts switched on."""
    utc_offset: timedelta = timedelta()
    """Fallback for cameras that write no offset into EXIF."""
    clock_offset: timedelta = timedelta()
    """Correction for a camera whose clock was set wrong, added to every capture time."""
    color: str = ""
    """Ring colour of the photo markers; assigned by position when unset."""
    exclude: frozenset[str] = frozenset()
    """File names that stay in the source folder but never reach the bundle."""


@dataclass(frozen=True)
class Tour:
    title: str
    track: tuple[Path, ...]
    """The recorded GPX files, in the order they were named."""
    labels: tuple[str, ...] = ()
    """Names for the riding days, in order. Empty when none are configured."""
    utc_offset: timedelta = timedelta()
    """Local time of the ride, relative to the UTC stamps in the track."""


@dataclass(frozen=True)
class Config:
    tour: Tour
    collections: list[Collection]


def slug(text: str) -> str:
    return _SLUG_STRIP.sub("-", text.lower()).strip("-") or "collection"


def _resolve(value: str, root: Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else root / path


def _track_files(value: object, root: Path, config: Path) -> tuple[Path, ...]:
    """The GPX files behind `track`: one file, a folder of them, or a list of both."""
    entries = [value] if isinstance(value, str) else value
    if not isinstance(entries, list) or not all(isinstance(entry, str) for entry in entries):
        raise ValueError(f"track in {config.name} must be a path or a list of paths")

    files: list[Path] = []
    for entry in entries:
        path = _resolve(entry, root)
        if path.is_dir():
            found = sorted({*path.glob("*.gpx"), *path.glob("*.GPX")})
            if not found:
                raise FileNotFoundError(f"track folder {path} holds no .gpx files")
            files.extend(found)
        elif path.is_file():
            files.append(path)
        else:
            raise FileNotFoundError(f"track {path} does not exist")

    if not files:
        raise ValueError(f"track in {config.name} names no file")
    return tuple(dict.fromkeys(files))


def _day_labels(value: object, config: Path) -> tuple[str, ...]:
    """Names for the riding days, in order."""
    if value is None:
        return ()
    if isinstance(value, list) and all(isinstance(entry, str) for entry in value):
        return tuple(value)
    raise ValueError(
        f'stages in {config.name} must be a list of names, e.g. ["Arrival", "Over the pass"]'
    )


def _read_tour(raw: dict, root: Path, config: Path) -> Tour:
    try:
        title, track = raw["title"], raw["track"]
    except KeyError as missing:
        raise ValueError(f"[tour] in {config.name} is missing {missing}") from None

    return Tour(
        title=title,
        track=_track_files(track, root, config),
        labels=_day_labels(raw.get("stages"), config),
        utc_offset=timedelta(hours=raw.get("utc_offset_hours", DEFAULT_UTC_OFFSET_HOURS)),
    )


def _read_collections(entries: list[dict], root: Path, config: Path, tour: Tour) -> list[Collection]:
    if not entries:
        raise ValueError(f"{config} holds no [[collection]] entries")

    collections: list[Collection] = []
    seen: set[str] = set()
    for position, entry in enumerate(entries):
        try:
            name, location = entry["name"], entry["location"]
        except KeyError as missing:
            raise ValueError(f"collection in {config.name} is missing {missing}") from None

        identifier = entry.get("id") or slug(name)
        if identifier in seen:
            raise ValueError(f"collection id {identifier!r} appears more than once")
        seen.add(identifier)

        path = _resolve(location, root)
        if not path.is_dir():
            raise NotADirectoryError(f"collection {name!r}: {path} does not exist")

        hours = entry.get("utc_offset_hours")
        collections.append(
            Collection(
                id=identifier,
                name=name,
                location=path,
                enabled=bool(entry.get("enabled", True)),
                utc_offset=timedelta(hours=hours) if hours is not None else tour.utc_offset,
                clock_offset=timedelta(minutes=entry.get("clock_offset_minutes", 0)),
                color=entry.get("color") or collection_color(position),
                exclude=frozenset(entry.get("exclude", ())),
            )
        )
    return collections


def _broken_toml(config: Path, text: str, broken: tomllib.TOMLDecodeError) -> str:
    """The parser gives line and column; showing the line itself is what helps."""
    message = f"{config.name} is not valid TOML: {broken}"
    where = re.search(r"at line (\d+)", str(broken))
    if where is None:
        return message
    number = int(where.group(1))
    lines = text.splitlines()
    if not 1 <= number <= len(lines):
        return message
    return f"{message}\n  {number:>4} | {lines[number - 1]}"


def load_config(config: Path, root: Path) -> Config:
    """Load the configuration and check that everything it names exists."""
    if not config.exists():
        raise FileNotFoundError(f"{config} is missing - it holds the tour and its collections")
    text = config.read_text(encoding="utf-8-sig")
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as broken:
        raise ValueError(_broken_toml(config, text, broken)) from None
    tour = _read_tour(raw.get("tour", {}), root, config)
    return Config(tour=tour, collections=_read_collections(raw.get("collection", []), root, config, tour))


def load_collection_photos(collection: Collection) -> list[Photo]:
    """Load a collection's photos and pin down their time offset.

    An offset written by the camera wins; otherwise the configured one applies.
    Every photo carries a concrete value afterwards, so matching never guesses.

    A configured `clock_offset` moves the capture times on top of that, for a
    camera that was running ahead or behind. The order stays as it was.
    """
    photos = [
        photo
        for photo in load_photos(collection.location, collection.id)
        if photo.name not in collection.exclude
    ]
    for photo in photos:
        if photo.offset is None:
            photo.offset = collection.utc_offset
        photo.taken += collection.clock_offset
    return photos
