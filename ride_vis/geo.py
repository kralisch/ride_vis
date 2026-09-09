"""Geometry helpers: distances on the globe."""

from __future__ import annotations

import math

EARTH_R = 6371008.8

Point = tuple[float, float]  # (lat, lon)


def haversine(a: Point, b: Point) -> float:
    """Distance between two WGS84 points, in metres."""
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(h))


def cumulative(points: list[Point]) -> list[float]:
    """Running distance at each point, in metres."""
    out = [0.0]
    for prev, cur in zip(points, points[1:]):
        out.append(out[-1] + haversine(prev, cur))
    return out
