#!/usr/bin/env python3
"""Render square basemap thumbnails over a fixed Indonesia extent.

Sources serve Web Mercator XYZ tiles. The extent below matches `homeCamera`
in wwwroot/init/simple.json; it is widened symmetrically in latitude so the
output is square without distorting or letterboxing the map.

    python3 scripts/make-basemap-thumbnails.py            # all sources
    python3 scripts/make-basemap-thumbnails.py rbi carto  # named sources
"""

import hashlib
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from urllib.request import Request, urlopen

from PIL import Image

CENTER = (119.0, -2.5)
SPAN = 46.0
SIZE = 128
OUT_DIR = Path(__file__).resolve().parent.parent / "wwwroot" / "images" / "basemaps"
USER_AGENT = "PikselTerriaMap-thumbnailer/1.0 (+https://github.com/piksel-ina)"

SOURCES = {
    "indo-osm": {
        "url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    },
    "indo-carto": {
        "url": "https://basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png",
    },
    "indo-esri": {
        "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    },
}

TILE = 256


def merc_x(lon):
    return (lon + 180.0) / 360.0


def merc_y(lat):
    return (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0


def inv_merc_y(y):
    return math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y))))


def square_window():
    cx, cy = merc_x(CENTER[0]), merc_y(CENTER[1])
    half = (SPAN / 360.0) / 2
    return cx - half, cy - half, cx + half, cy + half


def pick_zoom(span, min_pixels):
    for z in range(0, 20):
        if span * TILE * (2**z) >= min_pixels:
            return z
    return 19


CACHE_DIR = Path(__file__).resolve().parent / ".tile-cache"


def fetch(url, attempts=2, timeout=8):
    cached = CACHE_DIR / (hashlib.sha1(url.encode()).hexdigest() + ".tile")
    if cached.exists():
        return Image.open(BytesIO(cached.read_bytes())).convert("RGBA")

    for i in range(attempts):
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(req, timeout=timeout) as r:
                raw = r.read()
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cached.write_bytes(raw)
            return Image.open(BytesIO(raw)).convert("RGBA")
        except Exception:
            if i == attempts - 1:
                return None
            time.sleep(1)


def render(name, spec):
    x0, y0, x1, y1 = square_window()
    z = pick_zoom(x1 - x0, SIZE * 4)
    n = 2**z

    tx0, tx1 = int(x0 * n), int(math.ceil(x1 * n))
    ty0, ty1 = int(y0 * n), int(math.ceil(y1 * n))
    cols, rows = tx1 - tx0, ty1 - ty0

    canvas = Image.new("RGB", (cols * TILE, rows * TILE), (255, 255, 255))
    jobs = [
        (tx, ty)
        for ty in range(ty0, ty1)
        for tx in range(tx0, tx1)
    ]

    def one(job):
        tx, ty = job
        url = spec["url"].format(z=z, x=tx % n, y=ty)
        return job, fetch(url)

    missing = 0
    with ThreadPoolExecutor(max_workers=4) as ex:
        for (tx, ty), img in ex.map(one, jobs):
            if img is None:
                missing += 1
                continue
            canvas.paste(img, ((tx - tx0) * TILE, (ty - ty0) * TILE), img)

    left = (x0 * n - tx0) * TILE
    top = (y0 * n - ty0) * TILE
    side = (x1 - x0) * n * TILE
    crop = canvas.crop((round(left), round(top), round(left + side), round(top + side)))

    thumb = crop.resize((SIZE, SIZE), Image.LANCZOS)
    thumb = thumb.quantize(colors=192, method=Image.MEDIANCUT, dither=Image.FLOYDSTEINBERG)

    out = OUT_DIR / f"{name}.png"
    thumb.save(out, optimize=True)
    return out, z, out.stat().st_size, missing, len(jobs)


def main():
    wanted = sys.argv[1:] or list(SOURCES)
    unknown = [w for w in wanted if w not in SOURCES]
    if unknown:
        sys.exit(f"unknown source(s): {', '.join(unknown)}\navailable: {', '.join(SOURCES)}")

    x0, y0, x1, y1 = square_window()
    print(
        f"center {CENTER[0]}E {CENTER[1]}N  span {SPAN} deg  ->  "
        f"{CENTER[0] - SPAN / 2:.1f}..{CENTER[0] + SPAN / 2:.1f}E, "
        f"{inv_merc_y(y1):.1f}..{inv_merc_y(y0):.1f}N   {SIZE}x{SIZE}"
    )
    for name in wanted:
        out, z, size, missing, total = render(name, SOURCES[name])
        note = f"  ({missing}/{total} tiles missing)" if missing else ""
        print(f"  {out.name:<16} z{z}  {size / 1024:.1f} KB{note}")


if __name__ == "__main__":
    main()
