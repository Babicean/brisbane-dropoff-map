"""Small geometry helpers in a local flat projection (metres).

Brisbane-scale only: an equirectangular projection centred on the inner
city is accurate to well under a metre across the scope suburbs, which is
far better than the source data. Standard library only.
"""
from __future__ import annotations

import math
from bisect import bisect_right
from collections import defaultdict

LAT0 = -27.46
LON0 = 153.03
M_PER_DEG_LAT = 110_574.0
M_PER_DEG_LON = 111_320.0 * math.cos(math.radians(LAT0))


def to_xy(lon: float, lat: float) -> tuple[float, float]:
    return (lon - LON0) * M_PER_DEG_LON, (lat - LAT0) * M_PER_DEG_LAT


def to_lonlat(x: float, y: float) -> tuple[float, float]:
    return x / M_PER_DEG_LON + LON0, y / M_PER_DEG_LAT + LAT0


def line_parts(geometry: dict) -> list[list[list[float]]]:
    if not geometry:
        return []
    if geometry["type"] == "LineString":
        return [geometry["coordinates"]]
    if geometry["type"] == "MultiLineString":
        return geometry["coordinates"]
    return []


def point_segment_distance(px, py, ax, ay, bx, by) -> float:
    dx, dy = bx - ax, by - ay
    seg = dx * dx + dy * dy
    t = 0.0 if seg == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


class SegmentIndex:
    """Grid index of line segments for 'what's near this point' queries."""

    def __init__(self, cell: float = 40.0):
        self.cell = cell
        self.grid: dict[tuple[int, int], list[int]] = defaultdict(list)
        self.segs: list[tuple[float, float, float, float, object]] = []

    def add_line(self, pts: list[tuple[float, float]], tag: object) -> None:
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            i = len(self.segs)
            self.segs.append((ax, ay, bx, by, tag))
            x0, x1 = sorted((ax, bx))
            y0, y1 = sorted((ay, by))
            for gx in range(int(x0 // self.cell), int(x1 // self.cell) + 1):
                for gy in range(int(y0 // self.cell), int(y1 // self.cell) + 1):
                    self.grid[(gx, gy)].append(i)

    def near(self, x: float, y: float, radius: float):
        """Yield (distance, tag) for segments within radius of (x, y)."""
        seen = set()
        r = int(math.ceil(radius / self.cell))
        cx, cy = int(x // self.cell), int(y // self.cell)
        for gx in range(cx - r, cx + r + 1):
            for gy in range(cy - r, cy + r + 1):
                for i in self.grid.get((gx, gy), ()):
                    if i in seen:
                        continue
                    seen.add(i)
                    ax, ay, bx, by, tag = self.segs[i]
                    d = point_segment_distance(x, y, ax, ay, bx, by)
                    if d <= radius:
                        yield d, tag

    def covered(self, x: float, y: float, radius: float) -> bool:
        return next(self.near(x, y, radius), None) is not None


class Polyline:
    """A polyline in metres with stationing (distance along the line)."""

    def __init__(self, pts: list[tuple[float, float]]):
        self.pts = pts
        self.stations = [0.0]
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            self.stations.append(self.stations[-1] + math.hypot(bx - ax, by - ay))

    @property
    def length(self) -> float:
        return self.stations[-1]

    def project(self, px: float, py: float) -> tuple[float, float, float]:
        """Return (station, signed offset, distance). Offset > 0 means left of travel direction."""
        best = (math.inf, 0.0, 0.0)
        for i, ((ax, ay), (bx, by)) in enumerate(zip(self.pts, self.pts[1:])):
            dx, dy = bx - ax, by - ay
            seg = dx * dx + dy * dy
            if seg == 0:
                continue
            t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg))
            qx, qy = ax + t * dx, ay + t * dy
            d = math.hypot(px - qx, py - qy)
            if d < best[0]:
                cross = dx * (py - ay) - dy * (px - ax)
                side = 1.0 if cross > 0 else -1.0
                best = (d, self.stations[i] + t * math.sqrt(seg), side * d)
        d, station, offset = best
        return station, offset, d

    def point_at(self, s: float) -> tuple[float, float, float, float]:
        """Return (x, y, tx, ty): position and unit tangent at station s."""
        s = max(0.0, min(self.length, s))
        i = max(0, min(len(self.pts) - 2, bisect_right(self.stations, s) - 1))
        (ax, ay), (bx, by) = self.pts[i], self.pts[i + 1]
        seg = self.stations[i + 1] - self.stations[i]
        t = 0.0 if seg == 0 else (s - self.stations[i]) / seg
        tx, ty = (bx - ax, by - ay)
        n = math.hypot(tx, ty) or 1.0
        return ax + t * (bx - ax), ay + t * (by - ay), tx / n, ty / n

    def offset_points(self, s0: float, s1: float, offset: float, step: float = 2.0):
        """Sample points every `step` metres from s0 to s1, shifted left by `offset` metres."""
        if s1 < s0:
            s0, s1 = s1, s0
        n = max(1, int(math.ceil((s1 - s0) / step)))
        out = []
        for k in range(n + 1):
            s = s0 + (s1 - s0) * k / n
            x, y, tx, ty = self.point_at(s)
            out.append((x - ty * offset, y + tx * offset))
        return out


def point_in_rings(lon: float, lat: float, rings: list[list[list[float]]]) -> bool:
    """Even-odd test against all rings of a polygon (holes included)."""
    inside = False
    for ring in rings:
        n = len(ring)
        for i in range(n):
            x1, y1 = ring[i][0], ring[i][1]
            x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
            if (y1 > lat) != (y2 > lat):
                x = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
                if lon < x:
                    inside = not inside
    return inside


def polygon_rings(geometry: dict) -> list[list[list[list[float]]]]:
    """Return a list of polygons, each a list of rings, for Polygon or MultiPolygon."""
    if geometry["type"] == "Polygon":
        return [geometry["coordinates"]]
    if geometry["type"] == "MultiPolygon":
        return geometry["coordinates"]
    return []


def simplify(pts: list[tuple[float, float]], tolerance: float = 0.4) -> list[tuple[float, float]]:
    """Douglas-Peucker: drop points that sit within `tolerance` metres of a straight run."""
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        (ax, ay), (bx, by) = pts[i], pts[j]
        best, idx = 0.0, -1
        for k in range(i + 1, j):
            d = point_segment_distance(pts[k][0], pts[k][1], ax, ay, bx, by)
            if d > best:
                best, idx = d, k
        if best > tolerance:
            keep[idx] = True
            stack.extend(((i, idx), (idx, j)))
    return [p for p, k in zip(pts, keep) if k]
