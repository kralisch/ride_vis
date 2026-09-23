"""Presentation settings and the wording the app shows."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

BASEMAPS = ("light", "topo", "satellite", "relief", "streets", "osm")
FALLBACK_LANGUAGE = "en"


@dataclass(frozen=True)
class Ui:
    language: str
    locale: str
    """Number formatting, e.g. en-GB or de-DE."""
    basemap: str
    terrain: bool
    exaggeration: float
    strings: dict[str, str]
    basemap_names: dict[str, str]


def _read_language(code: str, lang_dir: Path) -> tuple[dict, list[str]]:
    path = lang_dir / f"{code}.toml"
    if not path.is_file():
        available = ", ".join(sorted(p.stem for p in lang_dir.glob("*.toml"))) or "none"
        raise FileNotFoundError(f"language {code!r} not found in {lang_dir} (available: {available})")
    raw = tomllib.loads(path.read_text(encoding="utf-8-sig"))

    # Fall back to English for anything a translation has not covered, so a
    # half-finished language file still yields a usable app.
    missing: list[str] = []
    if code != FALLBACK_LANGUAGE:
        base = tomllib.loads((lang_dir / f"{FALLBACK_LANGUAGE}.toml").read_text(encoding="utf-8-sig"))
        for section in ("ui", "basemaps"):
            filled = dict(base.get(section, {}))
            for key, value in raw.get(section, {}).items():
                filled[key] = value
            missing += [k for k in base.get(section, {}) if k not in raw.get(section, {})]
            raw[section] = filled
    return raw, missing


def load_ui(config: Path, lang_dir: Path) -> tuple[Ui, list[str]]:
    """Read ui.toml and the language it names. Also returns untranslated keys."""
    raw = tomllib.loads(config.read_text(encoding="utf-8-sig")) if config.exists() else {}
    code = raw.get("language", FALLBACK_LANGUAGE)
    language, missing = _read_language(code, lang_dir)

    basemap = raw.get("basemap", "satellite")
    if basemap not in BASEMAPS:
        raise ValueError(f"basemap must be one of {BASEMAPS}, not {basemap!r}")

    return (
        Ui(
            language=code,
            locale=language.get("locale", "en-GB"),
            basemap=basemap,
            terrain=bool(raw.get("terrain", True)),
            exaggeration=float(raw.get("exaggeration", 1.5)),
            strings=language.get("ui", {}),
            basemap_names=language.get("basemaps", {}),
        ),
        missing,
    )
