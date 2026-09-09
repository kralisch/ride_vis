"""Build the interactive map: the track as riding days, photos as markers."""

from __future__ import annotations

from datetime import timedelta
from string import Template
import folium
from folium.plugins import Fullscreen, MarkerCluster

from .match import GPS, OUTSIDE, TRACK_GAP, Placement
from .config import Collection
from .palette import CSS_DASHES, INK, INK_MUTED, SURFACE, day_style
from .route import Track

CSS = Template("""
.leaflet-div-icon { background:transparent; border:none; }
.rv-pin { position:relative; box-sizing:border-box; width:46px; height:46px; border-radius:50%;
  border:2.5px solid var(--rv-c); box-shadow:0 0 0 2px #fff, 0 2px 6px rgba(0,0,0,.35);
  background:#fff; transition:transform .12s ease; }
.rv-pin:hover { transform:scale(1.25); z-index:10000; }
/* Leaflet sets width:auto on images in the marker pane at higher specificity -
   without !important the thumbnail scales by height alone and turns oval. */
.rv-pin img { width:100% !important; height:100% !important; object-fit:cover;
  display:block; border-radius:50%; }
.rv-pin--gap { border-style:dashed; }
.rv-pin--outside { border-style:dotted; border-color:$muted; }
.rv-pin--gps::after { content:""; position:absolute; right:-1px; bottom:-1px;
  width:12px; height:12px; border-radius:50%; background:var(--rv-c);
  border:2px solid #fff; }
.rv-cluster { width:40px; height:40px; border-radius:50%; background:var(--rv-c);
  color:#fff; display:flex; align-items:center; justify-content:center;
  font:600 13px/1 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  border:2.5px solid #fff; box-shadow:0 2px 6px rgba(0,0,0,.35); }
.rv-pop { font:13px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; color:$ink; }
.rv-pop img { width:100%; border-radius:5px; display:block; }
.rv-pop .rv-sub { margin-top:6px; }
.rv-pop .rv-note { color:$muted; font-size:11.5px; margin-top:3px; }
.leaflet-popup-content { margin:11px !important; }
.rv-legend { position:fixed; left:14px; bottom:24px; z-index:9999; background:$surface;
  border:1px solid rgba(11,11,11,.12); border-radius:7px; padding:11px 13px;
  font:12px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; color:$ink;
  box-shadow:0 2px 10px rgba(0,0,0,.13); max-width:290px; }
.rv-legend h4 { margin:0 0 7px; font-size:12.5px; letter-spacing:.02em; }
.rv-legend h5 { margin:9px 0 4px; padding-top:7px; font-size:11px; font-weight:600;
  letter-spacing:.05em; text-transform:uppercase; color:$muted;
  border-top:1px solid rgba(11,11,11,.1); }
.rv-legend table { border-collapse:collapse; width:100%; }
.rv-legend td { padding:1.5px 0; vertical-align:middle; }
.rv-legend td.rv-km { text-align:right; color:$muted; padding-left:9px;
  font-variant-numeric:tabular-nums; }
.rv-legend svg { display:block; }
.rv-legend .rv-foot { margin-top:8px; padding-top:7px; border-top:1px solid rgba(11,11,11,.1);
  color:$muted; font-size:11.5px; }
""").substitute(ink=INK, muted=INK_MUTED, surface=SURFACE)


def _leaflet_style(index: int) -> tuple[str, str | None]:
    """Colour and stroke of a riding day, pattern in pixels for Leaflet."""
    color, dash = day_style(index)
    return color, CSS_DASHES[dash]


def _hhmm(delta: timedelta) -> str:
    total = int(delta.total_seconds())
    return f"{total // 3600}:{total % 3600 // 60:02d} h"


def _cluster(color: str) -> MarkerCluster:
    """Groups photos that sit close together until the map is zoomed in far enough."""
    return MarkerCluster(
        icon_create_function=(
            "function(cluster) { return L.divIcon({"
            f"html: '<div class=\"rv-cluster\" style=\"--rv-c:{color}\">'"
            " + cluster.getChildCount() + '</div>',"
            "className: '', iconSize: L.point(40, 40)}); }"
        ),
        options={
            "maxClusterRadius": 44,
            "spiderfyOnMaxZoom": True,
            "showCoverageOnHover": False,
            "disableClusteringAtZoom": 14,
        },
    )


def _marker(placement: Placement, assets: dict, color: str) -> folium.Marker:
    photo = placement.photo
    files = assets[photo.key]
    modifier = {GPS: "gps", TRACK_GAP: "gap", OUTSIDE: "outside"}.get(placement.source, "track")
    day_label = placement.day.label

    icon = folium.DivIcon(
        icon_size=(46, 46),
        icon_anchor=(23, 23),
        html=(
            f'<div class="rv-pin rv-pin--{modifier}" style="--rv-c:{color}">'
            f'<img src="{files["thumb"]}" loading="lazy" alt=""></div>'
        ),
    )
    popup = folium.Popup(
        f'<div class="rv-pop"><img src="{files["view"]}" loading="lazy" alt="">'
        f'<div class="rv-sub"><b>{photo.taken:%H:%M}</b> &middot; {photo.taken:%d.%m.%Y} '
        f'&middot; {day_label}</div>'
        f'<div class="rv-note">{photo.name}</div></div>',
        max_width=520,
    )
    return folium.Marker(
        location=placement.position,
        icon=icon,
        popup=popup,
        tooltip=f"{photo.taken:%d.%m. %H:%M} &middot; {day_label}",
    )


def _legend(track: Track, placements: list[Placement], collections: list[Collection], title: str) -> str:
    rows = []
    for day in track.days:
        color, dash = _leaflet_style(day.index)
        count = sum(1 for p in placements if p.day is day)
        stroke = f' stroke-dasharray="{dash}"' if dash else ""
        rows.append(
            f'<tr><td style="width:34px"><svg width="30" height="10">'
            f'<line x1="0" y1="5" x2="30" y2="5" stroke="{color}" stroke-width="3"{stroke}/>'
            f"</svg></td><td>{day.label}</td>"
            f'<td class="rv-km">{day.distance_m / 1000:.0f} km &middot; {count}</td></tr>'
        )
    sets = []
    for collection in collections:
        count = sum(1 for p in placements if p.photo.collection == collection.id)
        sets.append(
            f'<tr><td style="width:34px"><svg width="30" height="14">'
            f'<circle cx="15" cy="7" r="5.5" fill="{collection.color}" '
            f'stroke="#fff" stroke-width="1.5"/></svg></td>'
            f"<td>{collection.name}</td>"
            f'<td class="rv-km">{count}</td></tr>'
        )

    unplaced = sum(1 for p in placements if p.source == OUTSIDE)
    total = f"{track.distance_m / 1000:,.0f}".replace(",", ".")
    foot = f"{len(placements)} photos, {total} km. Positions derived from capture time."
    if unplaced:
        foot += f" Dotted ring: {unplaced} photos outside the recording."
    return (
        f'<div class="rv-legend"><h4>{title}</h4>'
        f"<table>{''.join(rows)}</table>"
        f'<h5>Collections</h5><table>{"".join(sets)}</table>'
        f'<div class="rv-foot">{foot}</div></div>'
    )


def build_map(
    track: Track,
    placements: list[Placement],
    assets: dict,
    collections: list[Collection],
    title: str,
) -> folium.Map:
    """Build the map with riding days and photo markers."""
    fmap = folium.Map(tiles=None, control_scale=True)
    # Order matters: the basemap added last is the one active on open. The muted
    # light backdrop is the surface the route colours were checked against;
    # topography and OSM are there to switch to.
    folium.TileLayer(
        tiles="https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
        attr="Map data &copy; OpenStreetMap contributors, SRTM | "
             "Style &copy; OpenTopoMap (CC-BY-SA)",
        name="Topographic",
        max_zoom=17,
    ).add_to(fmap)
    folium.TileLayer("openstreetmap", name="OpenStreetMap").add_to(fmap)
    # Muted grey with no colour fills of its own - the surface the two route
    # colours were checked against for contrast and colour blindness.
    # (CartoDB Positron would be the obvious pick but now only serves tiles
    # stamped "API key required".)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/"
              "World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
        attr="&copy; Esri, HERE, Garmin, &copy; OpenStreetMap contributors",
        name="Map (light)",
        max_zoom=16,
    ).add_to(fmap)

    set_colors = {c.id: c.color for c in collections}
    by_day = {}
    for placement in placements:
        by_day.setdefault(placement.day.index, []).append(placement)

    for day in track.days:
        color, dash = _leaflet_style(day.index)
        photos = by_day.get(day.index, [])
        group = folium.FeatureGroup(
            name=f"{day.label} &middot; {day.distance_m / 1000:.0f} km &middot; {len(photos)} photos",
            show=True,
        )
        line = [p.position for p in day.points]
        # White casing under the line: lifts it off the tiles and gives the
        # orange leg the separation it needs from the backdrop.
        folium.PolyLine(line, color="#ffffff", weight=7, opacity=0.85).add_to(group)
        folium.PolyLine(
            line,
            color=color,
            weight=3.5,
            opacity=1,
            dash_array=dash,
            tooltip=(
                f"{day.label} &middot; {day.distance_m / 1000:.0f} km &middot; "
                f"{_hhmm(day.duration)} &middot; {day.date:%d.%m.%Y}"
            ),
        ).add_to(group)
        cluster = _cluster(color).add_to(group)
        for placement in photos:
            # Ring colour = collection; the day is already in the line beneath it.
            _marker(placement, assets, set_colors[placement.photo.collection]).add_to(cluster)
        group.add_to(fmap)

    ends = folium.FeatureGroup(name="Start and finish", show=True)
    folium.Marker(
        track.points[0].position, tooltip="Start",
        icon=folium.Icon(color="green", icon="play", prefix="fa"),
    ).add_to(ends)
    folium.Marker(
        track.points[-1].position, tooltip="Finish",
        icon=folium.Icon(color="darkred", icon="flag-checkered", prefix="fa"),
    ).add_to(ends)
    ends.add_to(fmap)

    Fullscreen(title="Full screen", title_cancel="Exit full screen").add_to(fmap)
    folium.LayerControl(collapsed=False).add_to(fmap)

    fmap.get_root().header.add_child(folium.Element(f"<style>{CSS}</style>"))
    fmap.get_root().html.add_child(folium.Element(_legend(track, placements, collections, title)))
    lats = [p.lat for p in track.points]
    lons = [p.lon for p in track.points]
    fmap.fit_bounds([(min(lats), min(lons)), (max(lats), max(lons))])
    return fmap
