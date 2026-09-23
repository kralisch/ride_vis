# ride_vis

Put the photos of a ride onto the GPS track that recorded it, using nothing but
the time each shot was taken. The result is a static web app: the route as
riding days on 3D terrain, an elevation profile, a timeline of every photo, and
a lightbox that reaches the full-size image.

Several people's photo collections can be mixed and switched on and off
independently, which is the point when everyone on a trip carries a camera.

## Getting started

```bash
pip install -r requirements.txt
cp ride.example.toml ride.toml     # then edit it
python build_app.py --serve
```

| Command | Result |
|---|---|
| `python build_app.py --serve` | `app/` - web app with 3D terrain, profile and timeline |
| `python build_app.py --standalone` | the same, usable by double click without a server |
| `python build_map.py --open` | `out/map.html` - a single plain Leaflet map |

## Configuration

Everything lives in `ride.toml`; `ride.example.toml` is the template.

```toml
[tour]
title = "My ride"
track = "gpx/track.gpx"
stages = "gpx/stages"       # optional, only for day names
utc_offset_hours = 2        # optional, see below

[[collection]]
name = "My camera"
location = "data/camera"
```

Per collection: `id`, `enabled`, `color`, `exclude`, `utc_offset_hours` and
`clock_offset_minutes` are optional. `id` is derived from the name when unset
and shows up in file paths and deep links.

### One track or several

Recording per day is the normal case, so `track` takes more than one file:

```toml
track = "gpx/track.gpx"                       # one file
track = "gpx"                                 # every .gpx in the folder
track = ["gpx/day1.gpx", "gpx/day2.gpx"]      # or named one by one
```

They pool into a single ride. The order they are named in does not matter -
what orders the ride is the clock, and the night between two recordings is
what makes a riding day. Merging them beforehand is not only unnecessary, it
is the more dangerous route: tools that merge tracks like to rewrite the
timestamps, and those are what the photos hang on.

A file repeated under another name drops out; two different recordings of the
same hours stop the build, because they would double distance and climb.

```
Track   day1.gpx and navi_day1.gpx both cover 30.08. 07:54 to 30.08. 14:28 -
        the same ride twice would double its distance and climb
```

Every file needs timestamps. A planned route carries none and is refused - the
whole point is when you were where.

### Adding or removing photos

Always at the source, then build again - **not** in the finished `app/`. Each
photo owns four files there plus an entry in `tour.js` with position, day,
distance and elevation, and those only come from matching against the track.

A run with nothing changed takes well under a second; finished images are not
recomputed. Whatever lost its source is cleared out, and the build says how
much. To keep a photo in the source folder but out of the bundle, list it in
`exclude`.

## Language and presentation

Two files, kept apart on purpose: **what** to show and **how it is worded**.

`ui.toml` holds the presentation settings:

```toml
language = "en"        # picks lang/en.toml
basemap = "satellite"  # light | topo | satellite | relief | osm
terrain = true         # start tilted
exaggeration = 1.5     # 1 to 3
```

`lang/<language>.toml` holds every label the app and the Leaflet map show,
plus the number format:

```toml
locale = "en-GB"       # 1,431 km rather than 1.431 km

[ui]
days = "Days"
totals = "{distance} · {ascent} m climb · {days} days · {photos}"
```

English and German ship with the project. To add one, copy a file, translate
it, and point `language` at it. Anything a translation leaves out falls back to
English, and the build says which keys those were - so a half-finished file
still gives a working app.

Switching language is a rebuild of about a second: no image is touched, only
`tour.js` is written again.

## How photos reach the map

Capture time is local time, the track is UTC. Every photo is looked up in the
track and interpolated between the two points around it.

The offset is resolved per photo. If the camera writes `OffsetTimeOriginal`
into EXIF, that value wins. Otherwise the collection's `utc_offset_hours`
applies, or the tour's. Phones usually write one; dedicated cameras often do not.

Photos that carry GPS in EXIF are the cross-check: their real position is
compared against the one derived from time, and every build reports the result.

```
Check   32 photos with GPS: distance to the track position is 9 m in the middle, 32 m at worst
```

A wrong offset shows up here immediately. Where a photo has GPS, those
coordinates are used directly - they beat any interpolation.

### A camera clock that was set wrong

The time zone is one thing, a clock that was never set right is another. A
camera running seven minutes behind puts every one of its photos seven minutes
too early on the track - at 60 km/h that is seven kilometres off.

```toml
[[collection]]
name = "My camera"
location = "data/camera"
clock_offset_minutes = 7    # the camera was seven minutes behind
```

The value is added to every capture time of that collection, before anything
else happens with it: positive when the camera was behind, negative when it was
ahead. Each build repeats what it applied.

```
Set     My camera  #1baf7a   100 photos,   3 with GPS, clock +7 min
```

To find the value, take a photo of something the track pins down - arriving
somewhere, a hairpin, a pass sign - and compare its stamp against the moment
the track was there. Two or three of those agree quickly.

The ring around a marker shows where its position came from:

| Ring | Source |
|---|---|
| solid | interpolated from capture time, or GPS from the photo |
| dashed | interpolated across a gap in the recording |
| dotted | outside the recording - before a day began or after it ended |

## Colours

Two things on the map carry colour, and they must not get in each other's way:

| Element | Encoding |
|---|---|
| Route line | hue = direction of travel, stroke = day within it |
| Marker ring | hue = collection, pattern = provenance of the position |

The ring deliberately does **not** carry the day: that is already in the line
the marker sits on. Six days cannot be encoded by colour anyway - as categories
they fail the all-pairs check, and as an ordinal ramp the blue scale only yields
eight lightness steps above the 2:1 contrast floor where ten would be needed.

Collection colours therefore start past blue and orange: **aqua `#1baf7a`,
violet `#4a3aa7`, yellow `#eda100`**. They pass all-pairs among themselves
(worst CVD distance 9.1, 22.9 under normal vision) and keep their distance from
the route colours. Three checked colours cover three collections; a fourth
turns grey with a note at build time, because generated hues would not pass.
Set `color` yourself if you need more. See `ride_vis/palette.py`.

## Bundle

`app/` **is** the bundle - copy it, serve it, done. Two switches decide what
goes in.

`--full` picks what sits behind the link under the large image:

| Mode | Behind the link |
|---|---|
| `original` (default) | the untouched camera file |
| `half` | half the edge length, roughly a fifth of the bytes |
| `none` | nothing; the link is left out |

`--standalone` embeds the photo markers in `tour.js` so `index.html` works by
double click. Without it a web server is needed - `--serve` brings one along,
any static host will do.

Both switches describe the state of the bundle, not just the run: whatever a
previous mode left behind gets cleared out.

### What the reader needs

No Python and no backend - `app/` is HTML, CSS, JavaScript and images. Only a
browser with WebGL and internet access for the tiles (maps, imagery and
elevation from Esri, OpenTopoMap and AWS). Without a network the profile,
timeline and photos still work; the map stays empty. MapLibre ships in
`web/vendor/`, so no CDN is involved.

Browsers treat a file opened straight from disk as a foreign origin. Two places
run into that, both handled: the tour data arrives as `tour.js` rather than
through `fetch`, and `--standalone` embeds the markers, which MapLibre would
otherwise have to read into a canvas.

**Deep links:** `#stage=4` opens one day, `#photo=<file name>` a single image,
`#off=<id>,<id>` hides collections.

## Hosting

All paths are relative, so the app also runs from a subfolder such as
`https://name.github.io/ride_vis/`. `.nojekyll` is written for you.

A published page is public even when the repository is private. For personal
photos a host with access control is the better choice - Cloudflare Pages with
Access is free for a small group and, unlike GitHub Pages, has no site size
limit that rules out full-resolution images.

## What is not in the repository

Only the code lives here. Inputs and everything generated stay out:

| Path | Content |
|---|---|
| `ride.toml` | the ride and its collections; copy `ride.example.toml` |
| `gpx/` | the recorded track and any planned stage files |
| `data/` | the photo collections |
| `app/`, `out/` | the build output |

## Layout

| File | Job |
|---|---|
| `ride_vis/config.py` | read `ride.toml`, load tour and collections |
| `ride_vis/ui.py` | read `ui.toml` and the language file |
| `ride_vis/photos.py` | EXIF: capture time, offset and GPS |
| `ride_vis/route.py` | load the GPX track, split it into riding days |
| `ride_vis/match.py` | place photos on the track by time |
| `ride_vis/images.py` | previews, views, full sizes and round markers |
| `ride_vis/export.py` | `tour.js` and `tour.json` for the app |
| `ride_vis/render.py` | the plain Leaflet map |
| `ride_vis/palette.py` | colours and stroke patterns |
| `ride_vis/geo.py` | distances |
| `web/` | the app itself: `index.html`, `app.css`, `app.js` |
| `lang/` | wording per language |

## Pitfalls already settled

- **MapLibre symbol layers:** add the source first, register the markers with
  `addImage`, and add the layer last. Any other order builds the tiles without
  icons, and images handed over later do not fix it.
- **Grid column:** `#app` needs `grid-template-columns: minmax(0, 1fr)`.
  Otherwise the timeline with its hundreds of thumbnails drags the whole page
  out to a multiple of the window width, map and profile canvas included.
- **The `hidden` attribute** loses against any explicit `display`, hence the
  rule `[hidden] { display: none !important; }`.
