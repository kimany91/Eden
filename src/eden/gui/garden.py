"""The garden Eden shows while it works: a low-poly tree that grows with the work done.

The tree is generated once, with a fixed seed (the same tree every time), in the colours of
Eden's logo. Everything that grows carries the moment of its growth on a scale ``t`` from 0
(a seed in the soil) to 1 (the grown tree): a branch segment grows between its ``t0`` and
``t1``, a leaf opens between its own two moments. The GPU draws the tree from those numbers
and the current growth alone (see ``qml/shaders``), so nothing is recomputed while it grows,
and every part is drawn with one instanced mesh: a few draw calls for the whole garden.

The stages of the tree are set on the stages of Eden's work (``controller.py``):

    t 0    → 0.08   analysis: the seed sprouts, its first two leaves come out of the soil;
    t 0.08 → 0.40   FL Studio renders the parts: the stem grows, the first branch, its leaves;
    t 0.40 → 0.82   the mix: the tree grows, its branches multiply, the crown fills;
    t 0.82 → 1      the master and its checks: the last branches and leaves, the trunk thickens.

Pure numpy here; ``garden_qml.py`` hands these arrays to Qt Quick 3D.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import numpy as np

ASSETS = Path(__file__).resolve().parent.parent / "assets"
SEED = 11
TRUNK_HEIGHT = 3.9  # metres
# trunk height reached at moments of the growth: (t, height)
TRUNK_SCHEDULE = ((0.0, 0.0), (0.025, 0.0), (0.08, 0.32), (0.22, 1.35), (0.40, 2.05), (0.82, 3.55),
                  (0.90, TRUNK_HEIGHT))
BRANCH_SPEED = 15.0  # metres of branch per unit of t
GROWN = 0.97  # everything has grown by then (the master's end); the rest is the checks
LEAF_OPENING = 0.035  # t a leaf takes to open
COTYLEDON = (0.05, 0.085, 0.30, 0.38)  # the sprout's two first leaves: open, then wither once real leaves are out
STRIDE = 10  # floats per vertex: position, normal, colour (rgba)
TABLE = 20  # floats per instance: three rows of the transform, colour, custom data


@dataclass(frozen=True)
class Tree:
    seg_start: np.ndarray  # (n, 3) base of each branch segment
    seg_axis: np.ndarray  # (n, 3, 3) columns: x, y (along the segment), z
    seg_length: np.ndarray
    seg_radius: np.ndarray  # base radius when grown
    seg_taper: np.ndarray  # tip radius / base radius
    seg_t: np.ndarray  # (n, 2) growth moments
    leaf_pos: np.ndarray  # (m, 3) where the leaf's stalk joins the branch
    leaf_axis: np.ndarray  # (m, 3, 3) columns: width, length, face normal
    leaf_size: np.ndarray
    leaf_color: np.ndarray  # (m, 3)
    leaf_t: np.ndarray  # (m, 4) open from, open at, wither from, gone at
    apple_hang: np.ndarray  # (3,) the twig the apple hangs from
    heights: np.ndarray  # tree height at t = 0, 0.01 … 1 (camera framing)

    @property
    def apple_center(self) -> np.ndarray:
        """The apple hangs on its stalk under the twig, clear of the leaves."""
        return self.apple_hang - np.array([0.0, APPLE_RADIUS + APPLE_STALK, 0.0])


APPLE_RADIUS = 0.13
APPLE_STALK = 0.2  # from the apple's top to the twig


@cache
def palette() -> tuple[np.ndarray, np.ndarray]:
    """(trunk, crown) colours of Eden's logo, as rgb in 0..1."""
    data = json.loads((ASSETS / "tree.json").read_text(encoding="utf-8"))

    def rgb(part: str) -> np.ndarray:
        colors = sorted({t["color"] for t in data["triangles"] if t["part"] == part})
        return np.array([[int(c[i:i + 2], 16) / 255 for i in (1, 3, 5)] for c in colors])

    return rgb("trunk"), rgb("crown")


def trunk_moment(height: float) -> float:
    """When the trunk's tip reaches ``height`` (inverse of TRUNK_SCHEDULE)."""
    ts, hs = zip(*TRUNK_SCHEDULE, strict=True)
    return float(np.interp(height, hs[1:], ts[1:]))


def _frame(direction: np.ndarray, twist: float) -> np.ndarray:
    """Orthonormal frame whose y column is ``direction``, turned by ``twist`` around it."""
    y = direction / np.linalg.norm(direction)
    helper = np.array([1.0, 0.0, 0.0]) if abs(y[1]) > 0.9 else np.array([0.0, 1.0, 0.0])
    x = np.cross(helper, y)
    x /= np.linalg.norm(x)
    z = np.cross(x, y)
    c, s = math.cos(twist), math.sin(twist)
    return np.stack([c * x + s * z, y, -s * x + c * z], axis=1)


def _toward(direction: np.ndarray, target: np.ndarray, amount: float) -> np.ndarray:
    d = direction + amount * target
    return d / np.linalg.norm(d)


@cache
def grow_tree(seed: int = SEED) -> Tree:
    rng = np.random.default_rng(seed)
    segs: list[tuple] = []  # (start, direction, length, radius, taper, t0, t1)
    nodes: list[tuple] = []  # (position, moment, depth, outward direction, terminal)
    up = np.array([0.0, 1.0, 0.0])

    # -- the trunk: a slightly wandering leader, thick at the foot ------------------------------
    trunk_heights = [0.0, 0.32, 0.8, 1.3, 1.8, 2.3, 2.8, 3.25, 3.6, TRUNK_HEIGHT]
    lean = rng.normal(0, 0.05, 2)
    trunk = [np.array([0.0, 0.0, 0.0])]
    for h in trunk_heights[1:]:
        drift = lean * h + rng.normal(0, 0.03, 2) * h
        trunk.append(np.array([drift[0], h, drift[1]]))
    radius = lambda h: 0.24 * (1 - h / (TRUNK_HEIGHT * 1.12)) ** 1.3 + 0.025  # noqa: E731
    for a, b in zip(trunk[:-1], trunk[1:], strict=True):
        d = b - a
        segs.append((a, d / np.linalg.norm(d), float(np.linalg.norm(d)), radius(a[1]),
                     radius(b[1]) / radius(a[1]), trunk_moment(a[1]), trunk_moment(b[1])))
    nodes.append((trunk[-1], trunk_moment(TRUNK_HEIGHT), 1, up, True))

    # -- branches: spiralling out of the trunk (golden angle) towards a dome, like the logo's crown --
    crown_y, crown_reach, crown_rise = 2.9, 2.05, 1.45

    def dome(azimuth: float, elevation: float) -> np.ndarray:
        """Point of the crown's outline; elevation from -1 (its bottom) to 1 (its top)."""
        reach = crown_reach * math.sqrt(max(0.0, 1 - elevation ** 2))
        return np.array([reach * math.cos(azimuth), crown_y + crown_rise * elevation, reach * math.sin(azimuth)])

    def branch(start: np.ndarray, target: np.ndarray, r0: float, t_start: float, depth: int, pieces: int) -> None:
        """A branch bending towards ``target`` in ``pieces`` segments; side twigs off a main branch."""
        pos, t, r = start, t_start, r0
        piece = float(np.linalg.norm(target - start)) / pieces
        direction = _toward(target - start, up, 0.6)  # leaves the trunk a little upwards, then bends out
        for i in range(pieces):
            direction = _toward(direction, (target - pos) / np.linalg.norm(target - pos), 1.4)
            direction = _toward(direction, rng.normal(0, 0.12, 3), 1.0)
            end = pos + direction * piece
            r_end = r * (0.72 if i < pieces - 1 else 0.55)
            t_end = t + piece / BRANCH_SPEED
            segs.append((pos, direction, piece, r, r_end / r, t, t_end))
            terminal = i == pieces - 1
            nodes.append((end, t_end, depth + 1, direction, terminal))
            if depth == 1 and i < pieces - 1:
                for _ in range(rng.integers(1, 3)):
                    side = np.cross(direction, rng.normal(0, 1, 3))
                    side /= np.linalg.norm(side)
                    twig = _toward(_toward(side, direction, 0.9), up, 0.35)
                    reach = float(np.linalg.norm(target - start)) * rng.uniform(0.32, 0.45)
                    branch(end, end + twig * reach, r_end * 0.72, t_end + 0.006, depth + 1, 2)
            pos, t, r = end, t_end, r_end

    golden = math.radians(137.5)
    azimuth = rng.uniform(0, 2 * math.pi)
    for k, h in enumerate(trunk_heights[3:9]):
        j = trunk_heights.index(h)
        azimuth += golden + rng.normal(0, 0.15)
        elevation = -0.55 + 1.25 * (h - 1.3) / (3.6 - 1.3) + rng.normal(0, 0.05)
        branch(trunk[j], dome(azimuth, elevation) * 0.86, radius(h) * 0.62, trunk_moment(h) + 0.004, 1, 3)
        if k in (1, 3):  # a second branch on the other side at some heights: a fuller crown
            other = azimuth + math.pi + rng.normal(0, 0.3)
            branch(trunk[j], dome(other, elevation + 0.15) * 0.8, radius(h) * 0.5, trunk_moment(h) + 0.02, 1, 3)

    # -- leaves: clusters at the twigs' ends, a few along them --------------------------------
    _, crown_colors = palette()
    leaf_pos, leaf_axis, leaf_size, leaf_color, leaf_t = [], [], [], [], []

    def leaf(at: np.ndarray, out: np.ndarray, size: float, t0: float, t1: float,
             wither: tuple[float, float] = (2.0, 2.0)) -> None:
        length_dir = _toward(out, up, 0.35)
        normal_hint = _toward(up, rng.normal(0, 1, 3), 0.6)
        width = np.cross(normal_hint, length_dir)
        if np.linalg.norm(width) < 1e-6:
            width = np.cross(np.array([1.0, 0.0, 0.0]), length_dir)
        width /= np.linalg.norm(width)
        normal = np.cross(width, length_dir)
        leaf_pos.append(at)
        leaf_axis.append(np.stack([width, length_dir, normal], axis=1))
        leaf_size.append(size)
        leaf_color.append(crown_colors[rng.integers(len(crown_colors))])
        leaf_t.append((t0, t1, *wither))

    for pos, t, depth, direction, terminal in nodes:
        if depth < 2:
            continue
        count = int(rng.integers(20, 27)) if terminal else int(rng.integers(6, 10))
        spread = 0.34 if terminal else 0.2
        for _ in range(count):
            offset = rng.normal(0, spread / 1.8, 3)
            out = _toward(direction, offset, 2.5)
            at = pos + offset
            t0 = t + rng.uniform(0.002, 0.03)
            leaf(at, out, rng.uniform(0.24, 0.36), t0, t0 + LEAF_OPENING)
    # the trunk's top gets its own tuft
    top, t_top = trunk[-1], trunk_moment(TRUNK_HEIGHT)
    for _ in range(22):
        offset = rng.normal(0, 0.24, 3)
        leaf(top + offset, _toward(up, offset, 2.0), rng.uniform(0.2, 0.3), t_top + rng.uniform(0, 0.03),
             t_top + 0.03 + LEAF_OPENING)
    # the sprout's two first leaves, out of the soil before anything else
    stem_top = trunk[1]
    for side in (1.0, -1.0):
        out = np.array([side, 0.55, 0.15 * side])
        leaf(stem_top, out / np.linalg.norm(out), 0.16, COTYLEDON[0], COTYLEDON[1], COTYLEDON[2:])

    # -- the apple: under the outermost twig at mid crown, nothing beneath it ---------------
    candidates = [(np.hypot(p[0], p[2]), p) for p, _, depth, _, terminal in nodes
                  if terminal and depth >= 2 and 2.0 < p[1] < 3.0]
    apple_hang = max(candidates, key=lambda c: c[0])[1] if candidates else np.array([1.2, 2.4, 0.0])

    seg = list(zip(*segs, strict=True))
    starts, directions = np.array(seg[0]), np.array(seg[1])
    axes = np.stack([_frame(d, 0.0) for d in directions])  # same facets all along: closed joints
    seg_t = np.array([seg[5], seg[6]]).T
    leaf_moments = np.array(leaf_t)
    # what would grow during the checks is brought into the master's span: everything has grown by GROWN
    late = max(seg_t.max(), leaf_moments[:, :2].max())
    seg_t, leaf_moments[:, :2] = _squeeze(seg_t, late), _squeeze(leaf_moments[:, :2], late)
    heights = np.array([_height_at(starts, directions, np.array(seg[2]), seg_t, t) for t in np.linspace(0, 1, 101)])
    return Tree(starts, axes, np.array(seg[2]), np.array(seg[3]), np.array(seg[4]), seg_t,
                np.array(leaf_pos), np.array(leaf_axis), np.array(leaf_size), np.array(leaf_color),
                leaf_moments, apple_hang, heights)


def _squeeze(t: np.ndarray, late: float, start: float = 0.82) -> np.ndarray:
    """Moments after ``start`` scaled so that ``late`` lands on GROWN."""
    if late <= GROWN:
        return t
    return np.where(t > start, start + (t - start) * (GROWN - start) / (late - start), t)


def _height_at(starts: np.ndarray, directions: np.ndarray, lengths: np.ndarray, t: np.ndarray, at: float) -> float:
    """Height of the highest point the tree has grown to at moment ``at``."""
    started = at > t[:, 0]
    if not started.any():
        return 0.0
    grown = np.clip((at - t[:, 0]) / np.maximum(t[:, 1] - t[:, 0], 1e-6), 0, 1)[started]
    tips = starts[started] + directions[started] * (lengths[started] * grown)[:, None]
    return float(max(0.0, tips[:, 1].max()))


# -- meshes (flat-shaded facets, like the logo) --------------------------------------------------

def _facets(triangles: list[tuple[np.ndarray, np.ndarray, np.ndarray]], colors: list[np.ndarray]) -> np.ndarray:
    """Interleaved vertices (position, normal, rgba) of triangles, one flat normal per facet."""
    out = np.zeros((len(triangles) * 3, STRIDE), dtype=np.float32)
    for i, ((a, b, c), color) in enumerate(zip(triangles, colors, strict=True)):
        n = np.cross(b - a, c - a)
        n = n / (np.linalg.norm(n) or 1.0)
        for j, p in enumerate((a, b, c)):
            out[3 * i + j] = (*p, *n, *color, 1.0)
    return out


def branch_mesh(sides: int = 6) -> np.ndarray:
    """A straight prism, radius 1, from y = 0 to y = 1, closed at the top; the shader tapers it."""
    rng = np.random.default_rng(3)
    trunk_colors, _ = palette()
    ring = [np.array([math.cos(2 * math.pi * i / sides), 0.0, math.sin(2 * math.pi * i / sides)]) for i in range(sides)]
    top = np.array([0.0, 1.0, 0.0])
    tris, cols = [], []
    for i in range(sides):
        a, b = ring[i], ring[(i + 1) % sides]
        a1, b1 = a + top, b + top
        color = trunk_colors[rng.integers(len(trunk_colors))]
        tris += [(a, a1, b1), (a, b1, b)]
        cols += [color, color * 0.92]
        tris.append((a1, top, b1))
        cols.append(color * 1.05)
    return _facets(tris, cols)


def leaf_mesh() -> np.ndarray:
    """A folded diamond leaf from its stalk (origin) along +y, face towards +z, both sides drawn."""
    base, tip = np.array([0.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0])
    left, right = np.array([-0.36, 0.42, 0.05]), np.array([0.36, 0.42, 0.05])
    vein = np.array([0.0, 0.45, 0.12])
    front = [(base, vein, left), (left, vein, tip), (tip, vein, right), (right, vein, base)]
    shades = [1.0, 1.08, 0.94, 0.86]
    tris = list(front) + [(a, c, b) for a, b, c in front]
    cols = [np.full(3, s) for s in shades] + [np.full(3, s * 0.82) for s in shades]
    return _facets(tris, cols)


def _sphere(rows: int, cols: int, squash: float = 1.0) -> tuple[np.ndarray, list[tuple[int, int, int]]]:
    pts = [np.array([0.0, 1.0 * squash, 0.0])]
    for r in range(1, rows):
        phi = math.pi * r / rows
        for c in range(cols):
            th = 2 * math.pi * (c + 0.5 * (r % 2)) / cols
            pts.append(np.array([math.sin(phi) * math.cos(th), math.cos(phi) * squash, math.sin(phi) * math.sin(th)]))
    pts.append(np.array([0.0, -1.0 * squash, 0.0]))
    faces = []
    for c in range(cols):
        faces.append((0, 1 + (c + 1) % cols, 1 + c))
    for r in range(rows - 2):
        a0, b0 = 1 + r * cols, 1 + (r + 1) * cols
        for c in range(cols):
            c1 = (c + 1) % cols
            faces += [(a0 + c, a0 + c1, b0 + c), (a0 + c1, b0 + c1, b0 + c)]
    last = len(pts) - 1
    a0 = 1 + (rows - 2) * cols
    for c in range(cols):
        faces.append((last, a0 + c, a0 + (c + 1) % cols))
    return np.array(pts), faces


def apple_mesh() -> np.ndarray:
    """A faceted apple of radius APPLE_RADIUS centred on the origin, its stalk and a small leaf."""
    pts, faces = _sphere(7, 11, 0.92)
    pts = pts * APPLE_RADIUS
    pts[0, 1] -= APPLE_RADIUS * 0.22  # the hollow round the stalk
    red, deep, blush = np.array([0.80, 0.11, 0.12]), np.array([0.58, 0.05, 0.08]), np.array([0.93, 0.55, 0.10])
    rng = np.random.default_rng(5)
    tris, cols = [], []
    for f in faces:
        a, b, c = pts[list(f)]
        center = (a + b + c) / 3
        side = max(0.0, center[0] / APPLE_RADIUS)  # blushing on one side
        shade = red * (0.85 + 0.25 * rng.random()) if center[1] > -0.05 else deep * (0.9 + 0.2 * rng.random())
        tris.append((a, b, c))
        cols.append(shade * (1 - 0.6 * side) + blush * 0.6 * side)
    stalk_base = np.array([0.0, APPLE_RADIUS * 0.6, 0.0])
    stalk_top = np.array([0.015, APPLE_RADIUS + APPLE_STALK, 0.0])
    w = np.array([0.009, 0.0, 0.0])
    brown = np.array([0.36, 0.22, 0.06])
    tris += [(stalk_base - w, stalk_top - w * 0.6, stalk_top + w * 0.6), (stalk_base - w, stalk_top + w * 0.6, stalk_base + w)]
    cols += [brown, brown * 0.85]
    tris += [(stalk_base + w, stalk_top + w * 0.6, stalk_top - w * 0.6), (stalk_base + w, stalk_top - w * 0.6, stalk_base - w)]
    cols += [brown, brown * 0.85]
    _, crown_colors = palette()
    leaf = leaf_mesh().reshape(-1, STRIDE)
    leaf_pts = leaf[:, :3] * 0.09
    turn = _frame(np.array([0.8, 0.5, 0.2]), 0.4)
    leaf_pts = leaf_pts @ turn.T + stalk_base + (stalk_top - stalk_base) * 0.35
    for i in range(0, len(leaf_pts), 3):
        tris.append(tuple(leaf_pts[i:i + 3]))
        cols.append(crown_colors[2] * leaf[i, 6])
    return _facets(tris, cols)


def seed_mesh() -> np.ndarray:
    """The seed, half out of its mound of soil."""
    pts, faces = _sphere(4, 7, 0.6)
    rng = np.random.default_rng(6)
    tris, cols = [], []
    for f in faces:
        a, b, c = pts[list(f)] * np.array([0.05, 0.05, 0.035]) + np.array([0.0, 0.1, 0.0])
        tris.append((a, b, c))
        cols.append(np.array([0.50, 0.32, 0.12]) * rng.uniform(0.85, 1.1))
    return _facets(tris, cols)


def mound_mesh() -> np.ndarray:
    """The little mound of soil the tree grows from (ground level at y = 0)."""
    pts, faces = _sphere(5, 13, 0.16)
    rng = np.random.default_rng(7)
    pts = pts * (1 + rng.uniform(-0.06, 0.06, (len(pts), 1)))
    tris, cols = [], []
    for f in faces:
        a, b, c = pts[list(f)] * 0.55
        if min(a[1], b[1], c[1]) < -1e-6:
            continue
        tris.append((a, b, c))
        cols.append(np.array([0.24, 0.15, 0.08]) * rng.uniform(0.8, 1.15))
    return _facets(tris, cols)


def ground_mesh(radius: float = 18.0, rings: int = 15, sectors: int = 36) -> np.ndarray:
    """A faceted lawn, a little uneven (the tree grows from its own mound of soil)."""
    rng = np.random.default_rng(8)
    pts = [np.array([0.0, 0.0, 0.0])]
    for r in range(1, rings + 1):
        rr = radius * (r / rings) ** 1.6
        for s in range(sectors):
            th = 2 * math.pi * (s + rng.uniform(-0.3, 0.3) + 0.5 * (r % 2)) / sectors
            jitter = rr * (1 + rng.uniform(-0.04, 0.04))
            bump = rng.uniform(-0.05, 0.06) * min(1.0, rr / 2.5)
            pts.append(np.array([jitter * math.cos(th), bump, jitter * math.sin(th)]))
    tris, cols = [], []
    greens = [np.array(c) for c in ((0.07, 0.15, 0.08), (0.08, 0.18, 0.08), (0.10, 0.20, 0.10), (0.075, 0.16, 0.07))]

    def color(center: np.ndarray) -> np.ndarray:
        # calmer near the tree, where the facets meet in a fan
        calm = min(1.0, math.hypot(center[0], center[2]) / 3.0)
        pick = greens[rng.integers(len(greens))] if rng.random() < calm else greens[1]
        return pick * rng.uniform(1 - 0.12 * calm - 0.03, 1 + 0.1 * calm + 0.03)

    for s in range(sectors):
        a, b = pts[1 + s], pts[1 + (s + 1) % sectors]
        tris.append((pts[0], b, a))
        cols.append(color((pts[0] + a + b) / 3))
    for r in range(rings - 1):
        a0, b0 = 1 + r * sectors, 1 + (r + 1) * sectors
        for s in range(sectors):
            s1 = (s + 1) % sectors
            for f in ((a0 + s, b0 + s1, b0 + s), (a0 + s, a0 + s1, b0 + s1)):
                a, b, c = (pts[i] for i in f)
                tris.append((a, b, c))
                cols.append(color((a + b + c) / 3))
    return _facets(tris, cols)


def grass_mesh() -> np.ndarray:
    """A tuft of three blades (both sides), from the ground (origin) up to y = 1."""
    tris, cols = [], []
    for k in range(3):
        th = 2 * math.pi * k / 3 + 0.3
        d = np.array([math.cos(th), 0.0, math.sin(th)])
        side = np.array([-d[2], 0.0, d[0]]) * 0.09
        lean = d * 0.25
        a, b, tip = d * 0.05 - side, d * 0.05 + side, np.array([0.0, 1.0, 0.0]) + lean
        tris += [(a, tip, b), (a, b, tip)]
        cols += [np.full(3, 1.0), np.full(3, 0.8)]
    return _facets(tris, cols)


def flower_mesh() -> np.ndarray:
    """A small five-petal flower on a short stem (petals facing up)."""
    tris, cols = [], []
    heart = np.array([0.0, 1.0, 0.0])
    for k in range(5):
        th = 2 * math.pi * k / 5
        d = np.array([math.cos(th), 0.0, math.sin(th)])
        side = np.array([-d[2], 0.0, d[0]])
        tip = heart + d * 0.45 + np.array([0.0, 0.08, 0.0])
        tris += [(heart, heart + d * 0.2 + side * 0.18, tip), (heart, tip, heart + d * 0.2 - side * 0.18)]
        cols += [np.full(3, 1.0), np.full(3, 0.9)]
    center = [heart + np.array([0.08 * math.cos(a), 0.05, 0.08 * math.sin(a)]) for a in np.linspace(0, 2 * math.pi, 6)[:-1]]
    for i in range(5):
        tris.append((heart + np.array([0.0, 0.07, 0.0]), center[(i + 1) % 5], center[i]))
        cols.append(np.array([0.95, 0.55, 0.05]))
    stem = np.array([0.025, 0.0, 0.0])
    green = np.array([0.18, 0.40, 0.16])
    tris += [(-stem, heart + stem * 0.5, stem), (-stem, heart - stem * 0.5, heart + stem * 0.5),
             (stem, heart + stem * 0.5, -stem), (heart + stem * 0.5, heart - stem * 0.5, -stem)]
    cols += [green, green, green * 0.8, green * 0.8]
    return _facets(tris, cols)


def stone_mesh() -> np.ndarray:
    pts, faces = _sphere(3, 6, 0.6)
    rng = np.random.default_rng(4)
    pts = pts * (1 + rng.uniform(-0.18, 0.18, (len(pts), 1)))
    tris, cols = [], []
    for f in faces:
        a, b, c = pts[list(f)]
        tris.append((a, b, c))
        cols.append(np.full(3, rng.uniform(0.32, 0.42)))
    return _facets(tris, cols)


# -- instance tables ----------------------------------------------------------------------------

def _table(positions: np.ndarray, axes: np.ndarray, scales: np.ndarray, colors: np.ndarray,
           data: np.ndarray) -> np.ndarray:
    """Qt Quick 3D instance table: rows of [R · diag(scale) | position], colour, custom data."""
    n = len(positions)
    m = axes * scales[:, None, :]
    out = np.zeros((n, TABLE), dtype=np.float32)
    for row in range(3):
        out[:, 4 * row:4 * row + 3] = m[:, row, :]
        out[:, 4 * row + 3] = positions[:, row]
    out[:, 12:15] = colors
    out[:, 15] = 1.0
    out[:, 16:20] = data
    return out


def branch_table(tree: Tree) -> np.ndarray:
    """Per segment: custom data = (t0, t1, taper, 0); the mesh's unit length becomes the segment's,
    a little longer so that joints stay closed when the next segment turns."""
    n = len(tree.seg_start)
    scales = np.stack([tree.seg_radius, tree.seg_length + tree.seg_radius * tree.seg_taper * 0.5,
                       tree.seg_radius], axis=1)
    data = np.column_stack([tree.seg_t, tree.seg_taper, np.zeros(n)])
    return _table(tree.seg_start, tree.seg_axis, scales, np.ones((n, 3)), data)


def leaf_table(tree: Tree) -> np.ndarray:
    """Per leaf: custom data = (open from, open at, wither from, gone at)."""
    scales = np.repeat(tree.leaf_size[:, None], 3, axis=1)
    return _table(tree.leaf_pos, tree.leaf_axis, scales, tree.leaf_color, tree.leaf_t)


def scatter_table(kind: str, seed: int = 21) -> np.ndarray:
    """Grass tufts, flowers and stones spread over the lawn, never on the soil patch."""
    rng = np.random.default_rng(seed + {"grass": 0, "flowers": 1, "stones": 2}[kind])
    count, low, high = {"grass": (420, 0.55, 11.0), "flowers": (70, 1.1, 8.0), "stones": (14, 1.6, 9.0)}[kind]
    radius = np.sqrt(rng.uniform(low ** 2, high ** 2, count))
    angle = rng.uniform(0, 2 * math.pi, count)
    positions = np.column_stack([radius * np.cos(angle), np.full(count, -0.01), radius * np.sin(angle)])
    axes = np.stack([_frame(np.array([0.0, 1.0, 0.0]), a) for a in rng.uniform(0, 2 * math.pi, count)])
    if kind == "grass":
        size = rng.uniform(0.10, 0.24, count)
        scales = np.column_stack([size * 1.2, size, size * 1.2])
        greens = np.array([(0.20, 0.42, 0.16), (0.25, 0.48, 0.18), (0.30, 0.52, 0.20), (0.18, 0.36, 0.14)])
        colors = greens[rng.integers(len(greens), size=count)] * rng.uniform(0.7, 1.05, (count, 1))
    elif kind == "flowers":
        size = rng.uniform(0.07, 0.11, count)
        scales = np.column_stack([size, size * 1.4, size])
        tones = np.array([(1.0, 0.85, 0.15), (1.0, 0.95, 0.85), (0.98, 0.75, 0.10)])
        colors = tones[rng.integers(len(tones), size=count)]
    else:
        size = rng.uniform(0.08, 0.2, count)
        scales = np.column_stack([size * 1.3, size * 0.7, size])
        colors = np.ones((count, 3))
    return _table(positions, axes, scales, colors, np.zeros((count, 4)))


MESHES = {
    "branch": branch_mesh, "leaf": leaf_mesh, "apple": apple_mesh, "seed": seed_mesh, "mound": mound_mesh,
    "ground": ground_mesh, "grass": grass_mesh, "flower": flower_mesh, "stone": stone_mesh,
}
