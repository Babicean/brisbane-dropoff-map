#!/usr/bin/env python3
"""Turn the raw council layers into the GeoJSON files the map loads.

Reads data/raw/ (from fetch.py) and config/, writes web/data/:
    red.geojson        don't stop: painted lines and sign zones
    green.geojson      2-minute passenger drop-off is legal
    review.geojson     unclear: check the signs
    clearways.geojson  clearways with their hours
    points.geojson     signs we couldn't place on a street, and moderated notes
    cameras.geojson    parking camera streets and known camera positions
    areas.geojson      area outlines for the tabs, suburb names, suburb borders, landmarks
    meta.json          data dates, counts and quality checks

Features that only apply at certain times carry `sched` ("mask,start,end;...",
Brisbane time, Monday = bit 0) so the map can show what applies right now.

Standard library only. Exits non-zero if a data quality check fails, so a bad
council download never reaches the live map.
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hours  # noqa: E402
import zones  # noqa: E402
from geo import (Polyline, SegmentIndex, line_parts, point_in_rings, point_segment_distance,  # noqa: E402
                 polygon_rings, simplify, to_lonlat, to_xy)
from rules import (FINES, LOADING_LINE, LOADING_SIGN_TYPES, NOT_DRAWN_LINES,  # noqa: E402
                   NOT_DRAWN_SUBTYPES, RED_LINES, SIGN_RULES, norm)

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
CONFIG = ROOT / "config"
OUT = ROOT / "web" / "data"

SIGN_MATCH_METRES = 25      # a painted loading zone takes its type from a sign this close
COORD_DP = 6                # ~0.1 m
MIN_CONVENTION_AGREEMENT = 0.8
MIN_FEATURES = {"red": 1500, "green": 150}  # far fewer means a broken download


def load(name: str) -> list[dict]:
    path = RAW / f"{name}.geojson"
    if not path.exists():
        sys.exit(f"Missing {path}. Run pipeline/fetch.py first.")
    return json.loads(path.read_text(encoding="utf-8"))["features"]


def rnd(coords):
    if isinstance(coords[0], (int, float)):
        return [round(coords[0], COORD_DP), round(coords[1], COORD_DP)]
    return [rnd(c) for c in coords]


def feature(geom_type: str, coords, **props) -> dict:
    return {"type": "Feature", "geometry": {"type": geom_type, "coordinates": rnd(coords)},
            "properties": {k: v for k, v in props.items() if v not in (None, "", False)}}


def index_lines(features: list[dict]) -> SegmentIndex:
    idx = SegmentIndex(cell=30)
    for f in features:
        g = f["geometry"]
        parts = [g["coordinates"]] if g["type"] == "LineString" else g["coordinates"]
        for part in parts:
            idx.add_line([to_xy(*c[:2]) for c in part], True)
    return idx


def schedule_props(parsed, text: str, timed_kind: bool) -> dict:
    """Map a parsed schedule to feature properties (sched / hours / unclear)."""
    if parsed is None:
        return {"hours": text, "unclear": bool(text) or timed_kind}
    if parsed == hours.ALWAYS:
        return {"hours": text}
    if parsed == hours.OTHER_TIMES:
        return {"hours": text, "unclear": True}
    return {"hours": text, "sched": hours.encode(parsed)}


def label_with_flags(label: str, unclear: bool = False, open_ended: bool = False) -> str:
    if unclear:
        label += " · hours unclear, check the sign"
    if open_ended:
        label += " · end of zone estimated"
    return label


# --- Painted lines ------------------------------------------------------------

def painted_layers(lines, snapped_signs, poles_by_sign, chains):
    red, green, review = [], [], []
    skipped = Counter()
    loading_signs = [s for s in snapped_signs if s.kind in LOADING_SIGN_TYPES]
    for f in lines:
        p, geom = f["properties"], f.get("geometry")
        if not geom:
            skipped["no geometry"] += 1
            continue
        lifecycle = norm(p.get("ASSETLIFECYCLE"))
        kind = norm(p.get("PARKINGRESTRICTIONTYPE"))
        subtype = norm(p.get("PAVEMENTMARKINGSUBTYPE"))
        street = norm(p.get("STREET")).title()
        name = subtype if kind in ("", "Not Applicable") else kind
        gtype, coords = geom["type"], geom["coordinates"]

        if lifecycle == "Disposal Complete":
            skipped["removed from road"] += 1
            continue
        if lifecycle != "In Service":
            review.append(feature(gtype, coords, label=f"{name}: planned, may not be painted yet", street=street, src="paint"))
            continue
        if kind in NOT_DRAWN_LINES or subtype in NOT_DRAWN_SUBTYPES:
            skipped["parking bay or lane edge"] += 1
            continue
        if kind in RED_LINES:
            label, fine = RED_LINES[kind]
            red.append(feature(gtype, coords, label=label, street=street, fine=FINES[fine], src="paint"))
            continue
        if kind == LOADING_LINE:
            parts = [[to_xy(*c[:2]) for c in part] for part in line_parts(geom)]
            mid = parts[0][len(parts[0]) // 2]
            line_street = norm(p.get("STREET")).upper()
            best = None
            for s in loading_signs:
                # Same street and same side of the road as the painted zone.
                chain = chains[s.chain]
                if chain.street != line_street:
                    continue
                _, mid_offset, _ = chain.poly.project(*mid)
                if (mid_offset > 0) != (s.offset > 0):
                    continue
                for pts in parts:
                    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
                        d = point_segment_distance(s.x, s.y, ax, ay, bx, by)
                        if d <= SIGN_MATCH_METRES and (best is None or d < best[0]):
                            best = (d, s)
            if best is None:
                review.append(feature(gtype, coords, label="Loading zone: type unknown, check the sign", street=street, src="paint"))
                continue
            sign = best[1]
            layer, label, fine = SIGN_RULES[sign.kind]
            sched, hours_text, unclear, approximate = zones.sign_schedule(sign, poles_by_sign[id(sign)])
            if layer == "green" and (unclear or approximate):
                review.append(feature(gtype, coords, label=f"{label}: hours unclear, check the sign",
                                      street=street, hours=hours_text, src="paint"))
                continue
            target = green if layer == "green" else red
            target.append(feature(gtype, coords, label=label_with_flags(label, unclear), street=street,
                                  fine=FINES.get(fine), hours=hours_text, sched=sched, src="paint"))
            continue
        review.append(feature(gtype, coords, label=f"{name}: check the signs", street=street, src="paint"))
    return red, green, review, skipped


# --- Clearways ----------------------------------------------------------------

def clearway_layer(clearways):
    out, parse_stats = [], Counter()
    for c in clearways:
        if not c.get("geometry"):
            continue
        text = norm(c["properties"].get("OPERATIONAL_TIME"))
        parsed = hours.parse(text) if text else hours.ALWAYS
        parse_stats["always" if parsed == hours.ALWAYS else "unreadable" if parsed is None else "timed"] += 1
        props = schedule_props(parsed, text or "All times", timed_kind=True)
        out.append(feature(c["geometry"]["type"], c["geometry"]["coordinates"],
                           label=label_with_flags("Clearway: no stopping", props.get("unclear", False)),
                           fine=FINES["clearway"], hours=props.get("hours"), sched=props.get("sched")))
    return out, parse_stats


# --- Cameras ------------------------------------------------------------------

def camera_layer(chains, suburbs_geojson, live_suburbs):
    cfg = json.loads((CONFIG / "cameras.json").read_text(encoding="utf-8"))["cameras"]
    polys = {f["properties"]["SUBURB_NAME"]: polygon_rings(f["geometry"]) for f in suburbs_geojson["features"]}
    feats, placed, missing = [], 0, []
    for cam in cfg:
        if cam["suburb"] not in live_suburbs:
            continue
        status = cam["status"]
        if status == "unverified":
            continue  # claimed somewhere but no source found: tracked in config, not shown
        title = {"announced": "Council parking camera on this street",
                 "likely": "Likely parking camera on this street",
                 "reported": "Parking camera reported by a driver",
                 "confirmed": "Parking camera"}[status]
        props = dict(label=title, street=cam["street"].title(), status=status, source=cam.get("source"),
                     fine="Cameras catch illegal stops: no stopping and yellow lines, bus and taxi zones, clearways, and misuse of loading zones (over time, or commercial-only)")
        if cam.get("lon") is not None and cam.get("lat") is not None:
            feats.append(feature("Point", [cam["lon"], cam["lat"]], kind="pin", **props))
            placed += 1
            continue
        # No exact position yet: highlight the street within its suburb.
        rings = polys.get(cam["suburb"], [])
        best_mid, best_len = None, 0.0
        found = False
        for ch in chains:
            if ch.street != cam["street"]:
                continue
            mx, my, _, _ = ch.poly.point_at(ch.poly.length / 2)
            lon, lat = to_lonlat(mx, my)
            if not any(point_in_rings(lon, lat, poly) for poly in rings):
                continue
            found = True
            feats.append(feature("LineString", [list(to_lonlat(x, y)) for x, y in ch.poly.pts], kind="street", **props))
            if ch.poly.length > best_len:
                best_len, best_mid = ch.poly.length, [lon, lat]
        if found:
            feats.append(feature("Point", best_mid, kind="street_marker",
                                 note="Exact camera position not confirmed yet", **props))
            placed += 1
        else:
            missing.append(cam["id"])
    return feats, placed, missing


# --- Areas and landmarks --------------------------------------------------------

AREA_SIMPLIFY_M = 3      # area outlines only decide which tab is lit, so they can be rough
BORDER_SIMPLIFY_M = 1.5

# Screen sizes for keeping suburb names clear of other things (half width, half height, px).
NAME_CHAR_PX, NAME_LINE_PX, NAME_WRAP_PX = 9.4, 17, 104   # bold capitals, 13 px, wrap at 8 em
PIN_BOX_PX = (16, 16)        # camera pins are 30 px circles
LANDMARK_BOX_PX = (55, 9)    # a landmark's dot and name (the map can put the name either side)
# Metres per pixel at zoom 13.5 (MapLibre's tiles are 512 px), where the map gets busy;
# zoomed out further, the map can nudge a name to one side of its spot to dodge a pin.
# Names keep apart from each other at zoom 13, where the whole scope fits on a phone.
PIN_M_PER_PX = LANDMARK_M_PER_PX = 6.0
NAME_M_PER_PX = 8.5
NAME_CLEAR_PX = 4
EXTENT_TRIM = 0.02           # a tab frames the middle 96% of its area's kerbs, both ways


def _xy_ring(ring, tolerance):
    return simplify([to_xy(c[0], c[1]) for c in ring], tolerance)


def _lonlat(pts):
    return [list(to_lonlat(x, y)) for x, y in pts]


def _name_box(text):
    """Half width and height (px) of a suburb name as the map draws it, wrapped like MapLibre."""
    lines, line = [], ""
    for word in text.upper().split():
        joined = f"{line} {word}".strip()
        if line and len(joined) * NAME_CHAR_PX > NAME_WRAP_PX:
            lines.append(line)
            line = word
        else:
            line = joined
    lines.append(line)
    return max(len(s) for s in lines) * NAME_CHAR_PX / 2, len(lines) * NAME_LINE_PX / 2


def _label_spot(ring, box, obstacles):
    """Where a suburb's name fits best: the point deepest inside the suburb whose name box
    stays clear of landmarks and camera pins. `obstacles` are (x, y, half width px,
    half height px, metres per px). Coarse grid, then finer grids around the best point."""
    edges = list(zip(ring, ring[1:]))
    w, h = box

    def score(x, y):
        if not point_in_rings(x, y, [ring]):
            return -1e9
        clear = min((max(abs(ox - x) / m - (w + ow), abs(oy - y) / m - (h + oh))
                     for ox, oy, ow, oh, m in obstacles), default=0)
        if clear < NAME_CLEAR_PX:
            return clear - 1e6  # only if nowhere is clear: then the least crowded spot
        return min(point_segment_distance(x, y, ax, ay, bx, by) for (ax, ay), (bx, by) in edges)

    xs, ys = [p[0] for p in ring], [p[1] for p in ring]
    best_s, best_p = -1e10, ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
    half = max(max(xs) - min(xs), max(ys) - min(ys)) / 2
    for _ in range(3):
        step, (cx, cy) = half / 12, best_p
        for i in range(-12, 13):
            for j in range(-12, 13):
                s = score(cx + i * step, cy + j * step)
                if s > best_s:
                    best_s, best_p = s, (cx + i * step, cy + j * step)
        half = 2 * step
    return best_p


def _stitch(edges):
    """Join undirected edges (pairs of points) into as few polylines as possible."""
    adj = {}
    for a, b in edges:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    used, lines = set(), []

    def walk(start, nxt):
        line, prev, cur = [start, nxt], start, nxt
        used.add(frozenset((start, nxt)))
        while len(adj[cur]) == 2:
            follow = adj[cur][1] if adj[cur][0] == prev else adj[cur][0]
            if frozenset((cur, follow)) in used:
                break
            used.add(frozenset((cur, follow)))
            line.append(follow)
            prev, cur = cur, follow
        return line

    # Start at ends and junctions first, then whatever is left is a closed loop.
    for pass_loops in (False, True):
        for node, nbrs in adj.items():
            if pass_loops or len(nbrs) != 2:
                for nb in nbrs:
                    if frozenset((node, nb)) not in used:
                        lines.append(walk(node, nb))
    return lines


def areas_layer(suburbs_geojson, live_suburbs, pins, streets):
    """Areas for the tabs at the top of the map, a name label per suburb, suburb borders
    (each drawn once, none inside an area) and landmarks, all in one file. `pins` are the
    camera pin positions, which suburb names keep clear of; `streets` are the kerb lines,
    whose extent in each area is what a tab zooms to (a suburb's own outline runs out to
    the middle of the river)."""
    cfg = json.loads((CONFIG / "areas.json").read_text(encoding="utf-8"))
    marks = json.loads((CONFIG / "landmarks.json").read_text(encoding="utf-8"))["landmarks"]
    outer = {f["properties"]["SUBURB_NAME"]: polygon_rings(f["geometry"])
             for f in suburbs_geojson["features"] if f["properties"]["SUBURB_NAME"] in live_suburbs}

    groups, grouped = [], set()
    for area in cfg["areas"]:
        subs = [s for s in area["suburbs"] if s in outer]
        if subs:
            groups.append(dict(area, suburbs=subs))
            grouped.update(subs)
    for s in sorted(set(outer) - grouped):  # added to scope but not to areas.json: its own tab
        groups.append({"id": "-".join(s.lower().split()), "name": s.title(), "title": s.title(), "suburbs": [s]})
    area_of = {s: g["id"] for g in groups for s in g["suburbs"]}

    # Which area each kerb line is in (by its first point), for the extent a tab zooms to.
    extent = {g["id"]: [] for g in groups}
    for f in streets:
        first = line_parts(f["geometry"])[0][0]
        for s, polys in outer.items():
            if any(point_in_rings(first[0], first[1], poly) for poly in polys):
                extent[area_of[s]].extend(c for part in line_parts(f["geometry"]) for c in part)
                break

    feats = []
    for g in groups:
        polys, outline = [], []
        for s in g["suburbs"]:
            for poly in outer[s]:
                polys.append([_lonlat(_xy_ring(poly[0], AREA_SIMPLIFY_M))])
                outline.extend(poly[0])
        pts = extent[g["id"]] or outline
        lons, lats = sorted(p[0] for p in pts), sorted(p[1] for p in pts)
        lo, hi = int(len(pts) * EXTENT_TRIM), int(len(pts) * (1 - EXTENT_TRIM)) - 1
        bbox = [round(lons[lo], 5), round(lats[lo], 5), round(lons[hi], 5), round(lats[hi], 5)]
        feats.append(feature("MultiPolygon", polys, kind="area", id=g["id"], name=g["name"],
                             title=g.get("title") or g["name"], bbox=bbox))

    labels = cfg.get("labels", {})
    obstacles = ([(*to_xy(m["lon"], m["lat"]), *LANDMARK_BOX_PX, LANDMARK_M_PER_PX) for m in marks if m["suburb"] in outer]
                 + [(*to_xy(lon, lat), *PIN_BOX_PX, PIN_M_PER_PX) for lon, lat in pins])
    for s in [s for g in groups for s in g["suburbs"]]:  # tab order; each name keeps clear of the ones before
        conf = labels.get(s, {})
        text = conf.get("text") or s.title()
        box = _name_box(text)
        if conf.get("at"):
            at = conf["at"]
        else:
            biggest = max(outer[s], key=lambda poly: len(poly[0]))
            at = list(to_lonlat(*_label_spot(_xy_ring(biggest[0], 5), box, obstacles)))
        obstacles.append((*to_xy(*at), *box, NAME_M_PER_PX))
        feats.append(feature("Point", at, kind="label", text=text, suburb=s.title(), area=area_of[s]))

    # Borders: neighbouring suburbs share exact vertices, so an edge on two suburbs is a
    # shared border. Drop it inside an area, draw it once between areas.
    owners = {}
    for s, polys in outer.items():
        for poly in polys:
            for ring in poly:
                for a, b in zip(ring, ring[1:]):
                    ka, kb = (round(a[0], 7), round(a[1], 7)), (round(b[0], 7), round(b[1], 7))
                    if ka != kb:
                        owners.setdefault(frozenset((ka, kb)), set()).add(s)
    keep = [tuple(e) for e, subs in owners.items() if len({area_of[s] for s in subs}) == len(subs)]
    lines = [_lonlat(simplify([to_xy(*p) for p in line], BORDER_SIMPLIFY_M)) for line in _stitch(keep)]
    feats.append(feature("MultiLineString", lines, kind="border"))

    misplaced = []
    for m in marks:
        if m["suburb"] not in outer:
            continue  # outside the live scope: kept for later
        if not any(point_in_rings(m["lon"], m["lat"], poly) for poly in outer[m["suburb"]]):
            misplaced.append(m["name"])
        feats.append(feature("Point", [m["lon"], m["lat"]], kind="landmark", name=m["name"],
                             area=area_of[m["suburb"]]))
    return feats, {g["id"]: g["suburbs"] for g in groups}, misplaced


# --- Corrections --------------------------------------------------------------

def apply_corrections(layers: dict, points: list):
    cfg = json.loads((CONFIG / "corrections.json").read_text(encoding="utf-8"))["corrections"]
    hidden = 0
    for c in cfg:
        if c.get("action") == "note":
            points.append(feature("Point", [c["lon"], c["lat"]], layer="note", label=c.get("text", "Note from drivers")))
            continue
        if c.get("action") != "hide":
            continue
        cx, cy = to_xy(c["lon"], c["lat"])
        radius = float(c.get("radius_m", 15))
        for name, feats in layers.items():
            if c.get("layer") and c["layer"] != name:
                continue
            keep = []
            for f in feats:
                g = f["geometry"]
                parts = [g["coordinates"]] if g["type"] == "LineString" else g["coordinates"] if g["type"] == "MultiLineString" else [[g["coordinates"]]]
                near = any(math.dist((cx, cy), to_xy(*pt[:2])) <= radius for part in parts for pt in part)
                if near:
                    hidden += 1
                else:
                    keep.append(f)
            feats[:] = keep
    return hidden


# --- Green vs red ----------------------------------------------------------------

CONFLICT_M = 3.5        # green this close to red is on the same kerb
CONFLICT_SHARE = 0.3    # a timed red covering this share of a green trims the green's hours


def resolve_green_conflicts(green, reds):
    """Make sure nothing shows green where a red rule or clearway applies at the same time.

    Returns (green, extra_review, stats).
    - Timed red over a large share of a green: the red's hours are taken out of the green's.
    - Painted green: council's painted records overlap their neighbours by a few metres
      at the ends, so a painted green is only touched when always-on red runs along
      more than half of it; then it moves to review (conflicting records).
    - Sign-based green (inferred): any stretch under always-on red is cut away.
    """
    idx = SegmentIndex(cell=30)
    scheds, red_parts = [], []
    for i, f in enumerate(reds):
        g = f["geometry"]
        parts = []
        if g["type"] in ("LineString", "MultiLineString"):
            for part in ([g["coordinates"]] if g["type"] == "LineString" else g["coordinates"]):
                pts = [to_xy(*c[:2]) for c in part]
                parts.append(pts)
                idx.add_line(pts, i)
        red_parts.append(parts)
        scheds.append(hours.decode(f["properties"]["sched"]) if f["properties"].get("sched") else None)

    def alongside(x, y, i):
        """Is (x, y) beside red feature i, not just near one of its ends (1 m margin)?"""
        for pts in red_parts[i]:
            last = len(pts) - 2
            for j, ((ax, ay), (bx, by)) in enumerate(zip(pts, pts[1:])):
                dx, dy = bx - ax, by - ay
                seg2 = dx * dx + dy * dy
                if seg2 == 0:
                    continue
                t = ((x - ax) * dx + (y - ay) * dy) / seg2
                margin = 1.0 / math.sqrt(seg2)
                if (j == 0 and t < margin) or (j == last and t > 1 - margin):
                    continue
                t = max(0.0, min(1.0, t))
                if math.hypot(x - (ax + t * dx), y - (ay + t * dy)) <= CONFLICT_M:
                    return True
        return False

    out, extra_review, stats = [], [], Counter()
    for f in green:
        g = f["geometry"]
        parts = [g["coordinates"]] if g["type"] == "LineString" else g["coordinates"]
        samples = []
        for part in parts:
            pts = [to_xy(*c[:2]) for c in part]
            if len(pts) < 2:
                continue
            poly = Polyline(pts)
            samples.extend(poly.offset_points(0, poly.length, 0, step=2.0))
        if not samples:
            out.append(f)
            continue
        blocked, timed_hits = [], Counter()
        for x, y in samples:
            hit_always = False
            for _, i in idx.near(x, y, CONFLICT_M):
                if not alongside(x, y, i):
                    continue
                if scheds[i] is None:
                    hit_always = True
                else:
                    timed_hits[i] += 1
            blocked.append(hit_always)

        props = dict(f["properties"])
        green_sched = hours.decode(props["sched"]) if props.get("sched") else [(hours.ALL_DAYS, 0, 1440)]
        cut = [scheds[i] for i, n in timed_hits.items() if n / len(samples) >= CONFLICT_SHARE]
        if cut:
            remaining = hours.subtract(green_sched, *cut)
            if not remaining:
                stats["green removed: red at all its times"] += 1
                extra_review.append(dict(f, properties={**props, "label": props["label"] + ": conflicts with a timed rule, check the signs", "sched": None, "fine": None}))
                continue
            if remaining != hours.normalise(green_sched):
                props["sched"] = hours.encode(remaining)
                stats["green hours trimmed by timed red"] += 1

        share = sum(blocked) / len(samples)
        if props.get("src") == "paint":
            if share > 0.5:
                stats["painted green moved to review: red along most of it"] += 1
                extra_review.append(dict(f, properties={**props, "label": props["label"] + ": conflicting records, check the signs", "sched": None, "fine": None}))
            else:
                out.append(dict(f, properties=props))
            continue

        if not any(blocked):
            out.append(dict(f, properties=props))
            continue
        runs, run = [], []
        for pt, b in zip(samples, blocked):
            if b:
                if run:
                    runs.append(run)
                run = []
            else:
                run.append(pt)
        if run:
            runs.append(run)
        kept = 0
        for r in runs:
            if sum(math.dist(a, b) for a, b in zip(r, r[1:])) >= 6:
                out.append(feature("LineString", [list(to_lonlat(x, y)) for x, y in simplify(r)], **props))
                kept += 1
        stats["sign green cut back under always-on red"] += 1
        if not kept:
            stats["sign green removed: under always-on red"] += 1
    return out, extra_review, dict(stats)

# --- Main -----------------------------------------------------------------------

def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((RAW / "manifest.json").read_text(encoding="utf-8"))
    suburbs_geojson = json.loads((RAW / "suburbs.geojson").read_text(encoding="utf-8"))

    chains = zones.build_chains(load("roads"))
    snapped, loose = zones.snap_signs(load("signs"), chains)
    check = zones.validate_convention(snapped)
    if (check["agreement"] or 0) < MIN_CONVENTION_AGREEMENT:
        print(f"Arrow convention check failed: {check}", file=sys.stderr)
        return 1
    poles = zones.group_poles(snapped)
    poles_by_sign = {id(s): pole for kerb in poles.values() for pole in kerb for s in pole.signs}

    red, green, review, skipped = painted_layers(load("lines"), snapped, poles_by_sign, chains)
    painted_red, painted_any = index_lines(red), index_lines(red + green + review)

    zone_stats = Counter()
    for z in zones.build_zones(snapped, chains, convention=1):
        if z["layer"] == "green" and (z["unclear"] or z["approximate"]):
            # Never show green on a guess about hours.
            z = dict(z, layer="review", label=z["label"] + ": hours unclear, check the sign", fine=None, sched=None)
        cover = painted_red if z["layer"] == "red" else painted_any
        geoms = zones.zone_geometries(z, chains, cover)
        target = {"red": red, "green": green, "review": review}[z["layer"]]
        for coords in geoms:
            target.append(feature("LineString", coords,
                                  label=label_with_flags(z["label"], z["unclear"] and z["layer"] == "red", z["open"]),
                                  street=z["street"], fine=FINES.get(z["fine"]) if z["fine"] else None,
                                  hours=z["hours"], sched=z["sched"], src="sign"))
            zone_stats[z["layer"]] += 1

    points = []
    for s in loose:
        if s.rule:
            layer, label, fine = s.rule
            if layer == "green" and norm(s.props.get("PARKINGRESTRICTIONDAYSANDTIMES")):
                layer, label = "review", f"{label}: has set hours, check the sign"
            points.append(feature("Point", list(to_lonlat(s.x, s.y)), layer=layer,
                                  label=f"{label} (sign; couldn't place on a street)",
                                  street=norm(s.props.get("STREET")).title(), arrow=s.direction))

    clearways, clearway_parse = clearway_layer(load("clearways"))
    green, conflicted, conflict_stats = resolve_green_conflicts(green, red + clearways)
    review.extend(conflicted)
    cameras, cameras_placed, cameras_missing = camera_layer(chains, suburbs_geojson, set(manifest["suburbs"]))
    pins = [f["geometry"]["coordinates"] for f in cameras if f["geometry"]["type"] == "Point"]
    areas, area_groups, landmarks_misplaced = areas_layer(suburbs_geojson, set(manifest["suburbs"]), pins,
                                                          red + green + review + clearways)
    layers = {"red": red, "green": green, "review": review, "clearways": clearways}
    hidden = apply_corrections(layers, points)

    for name, minimum in MIN_FEATURES.items():
        if len(layers[name]) < minimum:
            print(f"Only {len(layers[name])} {name} features (expected at least {minimum}). "
                  "Not writing: the council download looks incomplete.", file=sys.stderr)
            return 1

    outputs = {**layers, "points": points, "cameras": cameras, "areas": areas}
    for name, feats in outputs.items():
        (OUT / f"{name}.geojson").write_text(
            json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8")

    meta = {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fetched_at": manifest["fetched_at"],
        "scope": manifest["scope"],
        "suburbs": [s.title() for s in manifest["suburbs"]],
        "areas": area_groups,
        "council_data_edited": {k: v["data_last_edit"] for k, v in manifest["layers"].items()},
        "counts": {k: len(v) for k, v in outputs.items()},
        "checks": {
            "arrow_convention": check,
            "signs_placed": len(snapped),
            "signs_not_placed": len(loose),
            "sign_zone_pieces": dict(zone_stats),
            "clearway_hours": dict(clearway_parse),
            "cameras_on_map": cameras_placed,
            "cameras_street_not_found": cameras_missing,
            "landmarks_outside_their_suburb": landmarks_misplaced,
            "features_hidden_by_corrections": hidden,
            "green_vs_red": conflict_stats,
            "painted_lines_skipped": dict(skipped),
        },
        "penalty_unit": "$172.70 from 1 July 2026",
    }
    (OUT / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")

    for name, feats in outputs.items():
        size = (OUT / f"{name}.geojson").stat().st_size / 1024
        print(f"  {name:<12}{len(feats):>6} features  {size:>7.0f} KB")
    print("  checks:", json.dumps(meta["checks"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
