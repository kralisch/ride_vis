"""Load the recorded track and split it into riding days."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import gpxpy

from .geo import Point, cumulative

DAY_BREAK = timedelta(hours=4)
"""A gap this long in the recording starts a new riding day."""

SEAM_TOLERANCE = timedelta(minutes=1)
"""Two recordings may touch where one was stopped and the next started."""


@dataclass
class TrackPoint:
    lat: float
    lon: float
    time: datetime
    """Timestamp in UTC, without tzinfo."""
    ele: float | None = None

    @property
    def position(self) -> Point:
        return (self.lat, self.lon)


@dataclass
class Day:
    index: int
    """1-based number of the riding day."""
    points: list[TrackPoint]
    label: str = ""
    cum: list[float] = field(init=False)
    """Running distance at each point, in metres."""
    times: list[datetime] = field(init=False)
    """Timestamps of the points, for bisect lookups."""

    def __post_init__(self) -> None:
        self.cum = cumulative([p.position for p in self.points])
        self.times = [p.time for p in self.points]
        if not self.label:
            self.label = f"Day {self.index}"

    @property
    def date(self) -> date:
        return self.points[0].time.date()

    @property
    def start(self) -> datetime:
        return self.points[0].time

    @property
    def end(self) -> datetime:
        return self.points[-1].time

    @property
    def distance_m(self) -> float:
        return self.cum[-1]

    @property
    def duration(self) -> timedelta:
        return self.end - self.start

    @property
    def ascent_m(self) -> float:
        """Total climb with a 3 m threshold against noise in the GPS elevation."""
        total, reference = 0.0, self.points[0].ele or 0.0
        for point in self.points:
            ele = point.ele
            if ele is None:
                continue
            if ele - reference >= 3:
                total += ele - reference
                reference = ele
            elif ele < reference:
                reference = ele
        return total


@dataclass
class Track:
    points: list[TrackPoint]
    days: list[Day]
    times: list[datetime] = field(init=False)
    """Timestamps of the points, for bisect lookups."""

    def __post_init__(self) -> None:
        self.times = [p.time for p in self.points]

    @property
    def start(self) -> datetime:
        return self.points[0].time

    @property
    def end(self) -> datetime:
        return self.points[-1].time

    @property
    def distance_m(self) -> float:
        return sum(day.distance_m for day in self.days)


def _split_days(points: list[TrackPoint]) -> list[Day]:
    groups: list[list[TrackPoint]] = [[points[0]]]
    for prev, cur in zip(points, points[1:]):
        if cur.time - prev.time >= DAY_BREAK:
            groups.append([])
        groups[-1].append(cur)
    return [Day(index=i, points=g) for i, g in enumerate(groups, start=1) if len(g) > 1]


def _read_points(path: Path) -> list[TrackPoint]:
    """The timed points of one file, in order."""
    gpx = gpxpy.parse(path.read_text(encoding="utf-8-sig"))
    points = [
        TrackPoint(lat=p.latitude, lon=p.longitude, time=p.time.replace(tzinfo=None), ele=p.elevation)
        for track in gpx.tracks
        for segment in track.segments
        for p in segment.points
        if p.time is not None
    ]
    if not points:
        raise ValueError(f"{path.name} holds no track points with a timestamp")
    points.sort(key=lambda p: p.time)
    return points


def _check_overlap(spans: list[tuple[datetime, datetime, Path]]) -> None:
    """Refuse two files that cover the same hours - they would count double."""
    spans.sort()
    for (_, end, earlier), (start, _, later) in zip(spans, spans[1:]):
        if start < end - SEAM_TOLERANCE:
            raise ValueError(
                f"{earlier.name} and {later.name} both cover "
                f"{start:%d.%m. %H:%M} to {end:%d.%m. %H:%M} - "
                f"the same ride twice would double its distance and climb"
            )


def load_track(paths: Path | Sequence[Path], labels: list[str] | None = None) -> Track:
    """Load the recorded track; only points carrying a timestamp count.

    Several files pool into one ride. Their order does not matter - the clock
    orders the ride, and the gap between two recordings is where a day ends.
    A file that only repeats points already read is a copy and drops out; two
    recordings of the same hours are an error, they would count double.
    """
    files = [paths] if isinstance(paths, Path) else list(paths)
    if not files:
        raise ValueError("no track file to read")

    spans: list[tuple[datetime, datetime, Path]] = []
    seen: set[tuple[datetime, float, float]] = set()
    points: list[TrackPoint] = []
    for path in files:
        found = _read_points(path)
        fresh = 0
        for point in found:
            key = (point.time, point.lat, point.lon)
            if key not in seen:
                seen.add(key)
                points.append(point)
                fresh += 1
        if fresh:
            spans.append((found[0].time, found[-1].time, path))
    _check_overlap(spans)
    points.sort(key=lambda p: p.time)

    days = _split_days(points)
    for day in days:
        if labels and day.index <= len(labels):
            day.label = labels[day.index - 1]
    return Track(points=points, days=days)
