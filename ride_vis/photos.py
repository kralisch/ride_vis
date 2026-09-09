"""Read photos: capture time and, where present, GPS position from EXIF."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from PIL import Image

EXIF_SUB_IFD = 0x8769
EXIF_GPS_IFD = 0x8825
TAG_DATETIME_ORIGINAL = 0x9003
TAG_OFFSET_TIME_ORIGINAL = 0x9011
GPS_LAT_REF, GPS_LAT, GPS_LON_REF, GPS_LON = 1, 2, 3, 4

SUFFIXES = {".jpg", ".jpeg", ".JPG", ".JPEG"}


@dataclass
class Photo:
    path: Path
    taken: datetime
    """Capture time as the camera's local time, without a zone."""
    gps: tuple[float, float] | None = None
    offset: timedelta | None = None
    """Time zone offset from EXIF, if the camera writes one."""
    collection: str = ""
    """id of the collection the photo came from."""

    @property
    def day(self) -> date:
        return self.taken.date()

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def key(self) -> str:
        """Unique across collections - file names repeat between cameras."""
        return f"{self.collection}/{self.path.name}" if self.collection else self.path.name


def _to_degrees(dms) -> float:
    d, m, s = (float(v) for v in dms)
    return d + m / 60 + s / 3600


def _read_offset(raw: str | None) -> timedelta | None:
    """Turn an EXIF offset such as "+02:00" into a time delta."""
    if not raw or len(raw) < 6 or raw[0] not in "+-":
        return None
    try:
        hours, minutes = int(raw[1:3]), int(raw[4:6])
    except ValueError:
        return None
    delta = timedelta(hours=hours, minutes=minutes)
    return -delta if raw[0] == "-" else delta


def _read_gps(exif) -> tuple[float, float] | None:
    gps = exif.get_ifd(EXIF_GPS_IFD)
    if not gps or GPS_LAT not in gps or GPS_LON not in gps:
        return None
    lat = _to_degrees(gps[GPS_LAT])
    lon = _to_degrees(gps[GPS_LON])
    if gps.get(GPS_LAT_REF) == "S":
        lat = -lat
    if gps.get(GPS_LON_REF) == "W":
        lon = -lon
    return (lat, lon)


def load_photo(path: Path, collection: str = "") -> Photo | None:
    """Read one photo; None when EXIF holds no capture time."""
    with Image.open(path) as im:
        exif = im.getexif()
        sub = exif.get_ifd(EXIF_SUB_IFD)
        raw = sub.get(TAG_DATETIME_ORIGINAL)
        offset = _read_offset(sub.get(TAG_OFFSET_TIME_ORIGINAL))
        gps = _read_gps(exif)
    if not raw:
        return None
    taken = datetime.strptime(raw, "%Y:%m:%d %H:%M:%S")
    return Photo(path=path, taken=taken, gps=gps, offset=offset, collection=collection)


def load_photos(directory: Path, collection: str = "") -> list[Photo]:
    """All photos in a folder, in chronological order."""
    photos = []
    for path in sorted(directory.iterdir()):
        if path.suffix not in SUFFIXES:
            continue
        photo = load_photo(path, collection)
        if photo is not None:
            photos.append(photo)
    return sorted(photos, key=lambda p: p.taken)
