"""Produce web-sized images - the originals run to several megabytes each."""

from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

THUMB_PX = 260
"""Edge length of the preview shown on the timeline."""
VIEW_PX = 1400
"""Edge length of the image shown in the lightbox."""

FULL_MODES = ("original", "half", "none")
"""What sits behind the link in the lightbox: the untouched file, a version at
half the edge length, or nothing."""

HALF_SCALE = 0.5
HALF_QUALITY = 88
HALF_DIR = "large"
"""Its own folder, so switching modes marks the other version as orphaned and
clears it out instead of leaving it behind."""

ORIENTATION_TAG = 0x0112
SWAPPED_ORIENTATIONS = {5, 6, 7, 8}
"""EXIF orientations where width and height are the other way round."""


def _pixel_size(path: Path) -> tuple[int, int]:
    """Size as displayed, that is with the EXIF orientation applied."""
    with Image.open(path) as im:
        width, height = im.size
        orientation = im.getexif().get(ORIENTATION_TAG, 1)
    return (height, width) if orientation in SWAPPED_ORIENTATIONS else (width, height)


def _render(src: Path, dst: Path, max_px: int, quality: int) -> None:
    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
        return
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)  # apply the camera orientation
        im.thumbnail((max_px, max_px), Image.LANCZOS)
        im.convert("RGB").save(dst, "JPEG", quality=quality, optimize=True)


def _render_scaled(src: Path, dst: Path, scale: float, quality: int) -> tuple[int, int]:
    """Scale to a fraction of the edge length; returns the resulting size."""
    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
        with Image.open(dst) as done:
            return done.size
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)
        size = (max(1, round(im.width * scale)), max(1, round(im.height * scale)))
        im = im.resize(size, Image.LANCZOS)
        im.convert("RGB").save(dst, "JPEG", quality=quality, optimize=True, progressive=True)
    return size


def _copy_original(src: Path, dst: Path) -> None:
    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
        return
    shutil.copy2(src, dst)


def prepare(photos, out_dir: Path, full: str = "original") -> dict[str, dict]:
    """Provide preview, view and - on request - full-size images.

    Returns the relative paths per photo key, exactly as the page refers to
    them. Every collection gets its own subfolder, because file names repeat
    between cameras without further ado.

    `full` decides what sits behind the link in the lightbox: `original` copies
    the camera file untouched, `half` scales it to half the edge length, `none`
    leaves the link out.
    """
    if full not in FULL_MODES:
        raise ValueError(f"full must be one of {FULL_MODES}, not {full!r}")

    assets: dict[str, dict] = {}
    for photo in photos:
        folder = photo.collection or "photos"
        name = photo.path.stem + ".jpg"
        extra = {"original": ("original",), "half": (HALF_DIR,), "none": ()}[full]
        for kind in ("thumbs", "photos") + extra:
            (out_dir / kind / folder).mkdir(parents=True, exist_ok=True)

        _render(photo.path, out_dir / "thumbs" / folder / name, THUMB_PX, quality=80)
        _render(photo.path, out_dir / "photos" / folder / name, VIEW_PX, quality=85)
        entry = {"thumb": f"thumbs/{folder}/{name}", "view": f"photos/{folder}/{name}"}

        if full == "original":
            target = out_dir / "original" / folder / photo.name
            _copy_original(photo.path, target)
            width, height = _pixel_size(photo.path)
            entry |= {
                "full": f"original/{folder}/{photo.name}",
                "fullW": width,
                "fullH": height,
                "fullBytes": target.stat().st_size,
            }
        elif full == "half":
            target = out_dir / HALF_DIR / folder / name
            width, height = _render_scaled(photo.path, target, HALF_SCALE, HALF_QUALITY)
            entry |= {
                "full": f"{HALF_DIR}/{folder}/{name}",
                "fullW": width,
                "fullH": height,
                "fullBytes": target.stat().st_size,
            }
        assets[photo.key] = entry
    return assets


MARKER_PX = 54
"""Display size of the round photo marker in the app."""
SCALE = 2
"""Markers are rendered at double size so they stay sharp on retina screens."""

RING_PX = 3
HALO_PX = 2
_RING_PATTERNS = {"solid": (1, 1.0), "dashed": (9, 0.55), "dotted": (24, 0.3)}
"""Ring pattern per provenance, as (segments, fraction drawn) - the same coding
as the border styles on the Leaflet map."""


def _circular_thumb(src: Path, size: int) -> Image.Image:
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)
        im = ImageOps.fit(im, (size, size), Image.LANCZOS, centering=(0.5, 0.5))
        im = im.convert("RGBA")
    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
    im.putalpha(mask.resize((size, size), Image.LANCZOS))
    return im


def _draw_ring(draw: ImageDraw.ImageDraw, box, color: str, width: int, pattern: str) -> None:
    segments, filled = _RING_PATTERNS[pattern]
    if segments == 1:
        draw.ellipse(box, outline=color, width=width)
        return
    step = 360 / segments
    for i in range(segments):
        start = i * step
        draw.arc(box, start, start + step * filled, fill=color, width=width)


def marker(src: Path, dst: Path, color: str, pattern: str) -> None:
    """Round photo marker with a coloured ring, white rim and soft shadow."""
    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
        return
    ring, halo = RING_PX * SCALE, HALO_PX * SCALE
    diameter = MARKER_PX * SCALE
    pad = 4 * SCALE                       # room for the shadow
    canvas_px = diameter + 2 * pad

    canvas = Image.new("RGBA", (canvas_px, canvas_px), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (canvas_px, canvas_px), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse(
        (pad, pad + SCALE, pad + diameter, pad + diameter + SCALE), fill=(0, 0, 0, 90)
    )
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(2 * SCALE)))

    draw = ImageDraw.Draw(canvas)
    draw.ellipse((pad, pad, pad + diameter, pad + diameter), fill="#ffffff")

    inset = pad + halo + ring
    photo_px = diameter - 2 * (halo + ring)
    canvas.alpha_composite(_circular_thumb(src, photo_px), (inset, inset))

    _draw_ring(
        draw,
        (pad + halo + ring / 2, pad + halo + ring / 2,
         pad + diameter - halo - ring / 2, pad + diameter - halo - ring / 2),
        color, ring, pattern,
    )
    canvas.save(dst, "PNG", optimize=True)
