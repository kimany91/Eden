"""Generate Eden's logo: a stylised low-poly yellow tree on a black background.

Outputs (in src/eden/assets/):
  eden-logo.svg   vector logo (also used by the interface)
  eden-logo.png   1024 px
  eden.ico        Windows icon, 16 to 256 px
  tree.json       triangle geometry, used by the animated splash screen

Deterministic: same seed, same logo.
"""

from __future__ import annotations

import colorsys
import json
import math
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy.spatial import Delaunay

OUT = Path(__file__).resolve().parent.parent / "src" / "eden" / "assets"
SIZE = 1024
SEED = 7

CROWN_CENTER = (512, 395)
CROWN_RX, CROWN_RY = 318, 278
LOBES = 7
# Trunk forking into two branches just under the crown
TRUNK = [(452, 905), (572, 905), (550, 790), (548, 700), (650, 610), (622, 590), (536, 650),
         (524, 560), (500, 560), (488, 650), (402, 590), (374, 610), (476, 700), (474, 790)]


def crown_outline(n: int = 42) -> list[tuple[float, float]]:
    """Symmetric lobed silhouette, slightly flattened at the bottom."""
    cx, cy = CROWN_CENTER
    pts = []
    for k in range(n):
        a = -math.pi / 2 + 2 * math.pi * k / n  # start at the top, symmetric about x = cx
        lobe = 1 + 0.075 * math.cos(LOBES * (a + math.pi / 2))
        ry = CROWN_RY * (0.86 if math.sin(a) > 0 else 1.0)
        pts.append((cx + CROWN_RX * lobe * math.cos(a), cy + ry * lobe * math.sin(a)))
    return pts


CROWN_POLY = crown_outline()


def in_crown(x: float, y: float, margin: float = 0) -> bool:
    if not point_in_poly(x, y, CROWN_POLY):
        return False
    if margin <= 0:
        return True
    return all(math.hypot(x - px, y - py) > margin for px, py in CROWN_POLY)


def point_in_poly(x: float, y: float, poly) -> bool:
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def crown_points(rng: random.Random) -> list[tuple[float, float]]:
    pts = list(CROWN_POLY)
    step = 64
    for gy in range(80, 720, step):
        for gx in range(150, 880, step):
            x, y = gx + rng.uniform(-24, 24), gy + rng.uniform(-24, 24)
            if in_crown(x, y, margin=34):
                pts.append((x, y))
    return pts


def facet_color(cx: float, cy: float, rng: random.Random, base_h: float, light: float,
                sat: float) -> str:
    # light from the top-left, with per-facet variation for the faceted look
    shade = 0.5 + 0.5 * (-(cx - 512) * 0.6 - (cy - 400) * 0.8) / 420
    lum = max(0.2, min(0.74, light + 0.34 * (shade - 0.5) + rng.uniform(-0.07, 0.07)))
    h = base_h + rng.uniform(-0.012, 0.012)
    r, g, b = colorsys.hls_to_rgb(h, lum, sat)
    return "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255))


def build() -> list[dict]:
    rng = random.Random(SEED)
    triangles = []

    pts = np.array(crown_points(rng))
    tri = Delaunay(pts)
    for simplex in tri.simplices:
        p = pts[simplex]
        cx, cy = p[:, 0].mean(), p[:, 1].mean()
        if not in_crown(cx, cy):
            continue
        triangles.append({"pts": [[round(float(x), 1), round(float(y), 1)] for x, y in p],
                          "color": facet_color(cx, cy, rng, 0.135, 0.52, 0.98),
                          "part": "crown", "order": float(math.hypot(cx - 512, cy - 420))})

    # trunk: triangulate polygon + interior points
    tpts = list(TRUNK)
    for _ in range(60):
        x, y = rng.uniform(380, 650), rng.uniform(560, 905)
        if point_in_poly(x, y, TRUNK):
            tpts.append((x, y))
    tarr = np.array(tpts)
    ttri = Delaunay(tarr)
    for simplex in ttri.simplices:
        p = tarr[simplex]
        cx, cy = p[:, 0].mean(), p[:, 1].mean()
        if not point_in_poly(cx, cy, TRUNK):
            continue
        triangles.append({"pts": [[round(float(x), 1), round(float(y), 1)] for x, y in p],
                          "color": facet_color(cx, cy, rng, 0.112, 0.43, 0.92),
                          "part": "trunk", "order": float(900 - cy)})
    # Grow order: trunk bottom-up first, then crown from the centre outwards
    trunk = sorted((t for t in triangles if t["part"] == "trunk"), key=lambda t: t["order"])
    crown = sorted((t for t in triangles if t["part"] == "crown"), key=lambda t: t["order"])
    return trunk + crown


def svg(triangles: list[dict], background: bool = True) -> str:
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SIZE} {SIZE}">']
    if background:
        out.append(f'<rect width="{SIZE}" height="{SIZE}" rx="200" fill="#000000"/>')
    for t in triangles:
        pts = " ".join(f"{x},{y}" for x, y in t["pts"])
        out.append(f'<polygon points="{pts}" fill="{t["color"]}" stroke="#000000" '
                   f'stroke-width="2" stroke-linejoin="round"/>')
    out.append("</svg>")
    return "\n".join(out)


def raster(triangles: list[dict], size: int) -> Image.Image:
    scale = 4
    big = SIZE * scale
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, big - 1, big - 1], radius=200 * scale, fill=(0, 0, 0, 255))
    for t in triangles:
        poly = [(x * scale, y * scale) for x, y in t["pts"]]
        d.polygon(poly, fill=t["color"], outline=(0, 0, 0, 255), width=2 * scale)
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    triangles = build()
    (OUT / "eden-logo.svg").write_text(svg(triangles), encoding="utf-8")
    (OUT / "tree.json").write_text(json.dumps(
        {"size": SIZE, "triangles": [{"pts": t["pts"], "color": t["color"], "part": t["part"]}
                                     for t in triangles]}), encoding="utf-8")
    raster(triangles, 1024).save(OUT / "eden-logo.png")
    raster(triangles, 256).save(OUT / "eden.ico",
                                sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                                       (128, 128), (256, 256)])
    print(f"{len(triangles)} triangles → {OUT}")


if __name__ == "__main__":
    main()
