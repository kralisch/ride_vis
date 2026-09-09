"""Load the recorded track and split it into riding days."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import gpxpy

from .geo import Point, cumulative

DAY_BREAK = timedelta(hours=4)
"""A gap this long in the recording starts a new riding day."""


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


def load_track(path: Path, labels: list[str] | None = None) -> Track:
    """Load a recorded GPX track; only points carrying a timestamp count."""
    gpx = gpxpy.parse(path.read_text(encoding="utf-8"))
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

    days = _split_days(points)
    for day in days:
        if labels and day.index <= len(labels):
            day.label = labels[day.index - 1]
    return Track(points=points, days=days)
