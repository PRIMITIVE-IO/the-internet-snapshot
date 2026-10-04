"""Icon atlases for clients (docs/snapshot-format.md §12).

The brand icons come from Simple Icons (CC0) and the function glyphs from Lucide (ISC). Both are
recoloured white so clients can tint them, written out as SVG, and rasterised into a PNG atlas
with a JSON UV map.
"""

from __future__ import annotations

import io
import json
import math
import re
import tarfile
from pathlib import Path

from ..sources import SOURCES
from ..sources import parsers as P

CELL = 64
PAD = 6


def _members(tgz: Path) -> dict[str, tarfile.TarInfo]:
    t = tarfile.open(tgz)
    return {m.name[len("package/icons/"):-4]: m for m in t.getmembers()
            if m.name.startswith("package/icons/") and m.name.endswith(".svg")}


def available_glyphs() -> set[str]:
    return set(_members(SOURCES["lucide"].path)) if SOURCES["lucide"].available() else set()


def available_brands() -> set[str]:
    return set(_members(SOURCES["simpleicons_svg"].path)) if SOURCES["simpleicons_svg"].available() else set()


def _white_glyph(svg: str) -> str:
    svg = re.sub(r"<!--.*?-->", "", svg, flags=re.S)
    return svg.replace('stroke="currentColor"', 'stroke="#FFFFFF"')


def _white_brand(svg: str) -> str:
    return svg.replace("<svg ", '<svg fill="#FFFFFF" ', 1)


def build_icons(out_dir: Path, glyphs: set[str], brands: set[str]) -> dict:
    """Write SVGs, a PNG atlas and index.json into out_dir. Returns the index."""
    import resvg_py
    from PIL import Image

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "glyphs").mkdir(exist_ok=True)
    (out_dir / "brands").mkdir(exist_ok=True)
    entries: list[tuple[str, str]] = []
    lucide = tarfile.open(SOURCES["lucide"].path)
    lm = _members(SOURCES["lucide"].path)
    for name in sorted(glyphs | {"circle"}):
        if name in lm:
            svg = _white_glyph(lucide.extractfile(lm[name]).read().decode())
            (out_dir / "glyphs" / f"{name}.svg").write_text(svg)
            entries.append((f"glyph:{name}", svg))
    brand_colors = {}
    if SOURCES["simpleicons_svg"].available():
        si = tarfile.open(SOURCES["simpleicons_svg"].path)
        sm = _members(SOURCES["simpleicons_svg"].path)
        colors = P.load_simpleicons(SOURCES["simpleicons"].path) if SOURCES["simpleicons"].available() else {}
        for slug in sorted(brands):
            if slug in sm:
                svg = _white_brand(si.extractfile(sm[slug]).read().decode())
                (out_dir / "brands" / f"{slug}.svg").write_text(svg)
                entries.append((f"brand:{slug}", svg))
                if slug in colors:
                    brand_colors[slug] = colors[slug]

    per_row = max(1, math.ceil(math.sqrt(len(entries))))
    size = 1 << math.ceil(math.log2(per_row * CELL))
    per_row = size // CELL
    rows = math.ceil(len(entries) / per_row)
    height = 1 << math.ceil(math.log2(max(CELL, rows * CELL)))
    atlas = Image.new("RGBA", (size, height), (0, 0, 0, 0))
    cells = {}
    for i, (name, svg) in enumerate(entries):
        x, y = (i % per_row) * CELL, (i // per_row) * CELL
        png = resvg_py.svg_to_bytes(svg_string=svg, width=CELL - 2 * PAD, height=CELL - 2 * PAD)
        atlas.paste(Image.open(io.BytesIO(bytes(png))).convert("RGBA"), (x + PAD, y + PAD))
        cells[name] = [x, y]
    atlas.save(out_dir / f"atlas-{CELL}.png", optimize=True)
    index = {
        "atlases": [{"file": f"icons/atlas-{CELL}.png", "cell": CELL, "width": size, "height": height,
                     "cells": cells}],
        "svg": {"glyph": "icons/glyphs/{name}.svg", "brand": "icons/brands/{name}.svg"},
        "brand_colors": brand_colors,
        "licenses": {"glyph": "Lucide (ISC), https://lucide.dev",
                     "brand": "Simple Icons (CC0), https://simpleicons.org; logos are trademarks of their owners"},
    }
    (out_dir / "index.json").write_text(json.dumps(index, separators=(",", ":")))
    return index
