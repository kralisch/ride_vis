"""Colours and stroke patterns of the visualisation.

Six days cannot be encoded by colour: as categories they fail the all-pairs
check, and as an ordinal ramp the blue scale only yields eight lightness steps
above the 2:1 contrast floor where ten would be needed. So hue carries the
direction of travel and the stroke pattern carries the day within it.
The pair is validated against the grey basemap #efefef and passes every check.
"""

from __future__ import annotations

OUTBOUND = "#2a78d6"
"""First half of an out-and-back ride."""
INBOUND = "#eb6834"
"""Return leg."""

DASH_NAMES = ["solid", "dashed", "dotted"]
DASH_ARRAYS: dict[str, list[float] | None] = {
    "solid": None,
    "dashed": [2.4, 1.6],
    "dotted": [0.35, 1.4],
}
"""Stroke patterns as multiples of the line width (MapLibre `line-dasharray`)."""

CSS_DASHES = {"solid": None, "dashed": "14,9", "dotted": "2,8"}
"""The same patterns in pixels, for SVG and Leaflet."""

INK = "#0b0b0b"
INK_MUTED = "#52514e"
SURFACE = "#fcfcfb"
BASEMAP_SURFACE = "#efefef"
"""Backdrop of the light basemap - the surface the colours were checked against."""

COLLECTION_COLORS = ["#1baf7a", "#4a3aa7", "#eda100"]
"""Colour per photo collection - aqua, violet, yellow.

A photo marker's ring carries its collection, not the day: the day is already
in the line the marker sits on. Blue and orange belong to the direction of
travel, so collections start at aqua.

Validated with `--pairs all`: worst CVD distance 9.1, 22.9 under normal vision.
Also separated from the route colours (worst CVD case: aqua to orange 9.2,
violet to blue 13.0, yellow to orange 9.7). A marker's contrast against the
backdrop comes from its white rim, not from the hue.
"""

COLLECTION_NEUTRAL = "#52514e"
"""From the fourth collection on: grey rather than an invented hue. Anyone who
needs more sets `color` in the configuration - generated hues would fail the
check."""

DAYS_PER_DIRECTION = 3


def day_style(index: int) -> tuple[str, str]:
    """Colour and stroke pattern of a riding day (1-based)."""
    outbound = index <= DAYS_PER_DIRECTION
    return (
        OUTBOUND if outbound else INBOUND,
        DASH_NAMES[(index - 1) % DAYS_PER_DIRECTION],
    )


def direction(index: int) -> str:
    return "outbound" if index <= DAYS_PER_DIRECTION else "inbound"


def collection_color(index: int) -> str:
    """Colour of the nth collection (0-based)."""
    if index < len(COLLECTION_COLORS):
        return COLLECTION_COLORS[index]
    return COLLECTION_NEUTRAL
