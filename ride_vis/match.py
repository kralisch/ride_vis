"""Place photos on the recorded track by their capture time."""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from datetime import datetime, timedelta

from .geo import Point, haversine
from .photos import Photo
from .route import Day, Track

UNCERTAIN_GAP = timedelta(minutes=5)
"""Interpolating across a longer gap makes the position uncertain."""

GPS = "gps"
TRACK = "track"
TRACK_GAP = "track-gap"
OUTSIDE = "outside"


@dataclass
class Fix:
    """A point on a riding day, derived from a moment in time."""

    position: Point
    elevation: float | None
    distance_m: float
    """Distance from the start of the day."""
    gap: timedelta
    """Spacing of the two track points around the moment."""


@dataclass
class Placement:
    photo: Photo
    position: Point
    day: Day
    """The riding day the photo belongs to - for shots outside the recording,
    the nearest one in time."""
    source: str
    """`gps`, `track`, `track-gap` or `outside`."""
    elevation: float | None = None
    distance_m: float = 0.0
    gap: timedelta | None = None
    gps_deviation_m: float | None = None
    """For photos with GPS: distance between the EXIF position and the track."""

    @property
    def utc(self) -> datetime:
        return utc_of(self.photo)


def utc_of(photo: Photo) -> datetime:
    """Capture time in UTC - the common ground with the track."""
    return photo.taken - (photo.offset or timedelta())


def _lerp(a: float | None, b: float | None, f: float) -> float | None:
    if a is None or b is None:
        return a if b is None else b
    return a + f * (b - a)


def interpolate(day: Day, when: datetime) -> Fix:
    """Position, elevation and distance along the day at `when`."""
    i = min(max(bisect_left(day.times, when), 1), len(day.points) - 1)
    before, after = day.points[i - 1], day.points[i]
    gap = after.time - before.time
    span = gap.total_seconds()
    f = (when - before.time).total_seconds() / span if span else 0.0
    f = min(max(f, 0.0), 1.0)
    return Fix(
        position=(
            before.lat + f * (after.lat - before.lat),
            before.lon + f * (after.lon - before.lon),
        ),
        elevation=_lerp(before.ele, after.ele, f),
        distance_m=day.cum[i - 1] + f * (day.cum[i] - day.cum[i - 1]),
        gap=gap,
    )


def _day_of(track: Track, when: datetime) -> Day | None:
    for day in track.days:
        if day.start <= when <= day.end:
            return day
    return None


def _nearest_day(track: Track, when: datetime) -> Day:
    return min(track.days, key=lambda d: min(abs(when - d.start), abs(when - d.end)))


def place_photos(photos: list[Photo], track: Track) -> list[Placement]:
    """Place every photo, in chronological order."""
    placements = []
    for photo in photos:
        when = utc_of(photo)
        day = _day_of(track, when)

        if day is None:
            # Before the first recording, after the last, or overnight:
            # nobody was riding at that moment.
            near = _nearest_day(track, when)
            before_start = when < near.start
            anchor = near.points[0] if before_start else near.points[-1]
            placements.append(
                Placement(
                    photo=photo,
                    position=photo.gps or anchor.position,
                    day=near,
                    source=GPS if photo.gps else OUTSIDE,
                    elevation=anchor.ele,
                    distance_m=0.0 if before_start else near.distance_m,
                )
            )
            continue

        fix = interpolate(day, when)
        if photo.gps is not None:
            placements.append(
                Placement(
                    photo=photo,
                    position=photo.gps,
                    day=day,
                    source=GPS,
                    elevation=fix.elevation,
                    distance_m=fix.distance_m,
                    gap=fix.gap,
                    gps_deviation_m=haversine(photo.gps, fix.position),
                )
            )
        else:
            placements.append(
                Placement(
                    photo=photo,
                    position=fix.position,
                    day=day,
                    source=TRACK if fix.gap <= UNCERTAIN_GAP else TRACK_GAP,
                    elevation=fix.elevation,
                    distance_m=fix.distance_m,
                    gap=fix.gap,
                )
            )
    return sorted(placements, key=lambda p: p.photo.taken)


def verify_offset(photos: list[Photo], track: Track) -> list[tuple[str, float]]:
    """Cross-check the time offset: how far GPS photos sit from the track, in metres."""
    out = []
    for photo in photos:
        if photo.gps is None:
            continue
        when = utc_of(photo)
        day = _day_of(track, when)
        if day is None:
            continue
        out.append((photo.key, haversine(photo.gps, interpolate(day, when).position)))
    return out
