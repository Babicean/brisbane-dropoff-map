"""Turn kerbside sign points into stretches of kerb.

A parking sign's arrow says which way its rule runs along the kerb. We:
  1. join council road centreline pieces into blocks (intersection to intersection),
  2. snap each sign to its street's centreline, recording which side it's on,
  3. turn the arrow into a direction along the centreline,
  4. run the rule from the sign to the next sign on that side, or to the end of the block.

Arrow convention: you read a sign standing on the road, facing the kerb. For a sign
on the left of the centreline's drawing direction, its right arrow points along that
direction; on the right-hand side it points the other way. validate_convention()
checks this on every build using pairs of matching signs.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

import hours
from geo import Polyline, SegmentIndex, line_parts, simplify, to_lonlat, to_xy
from rules import norm, sign_rule, ends_zones

SNAP_SAME_STREET_M = 35   # a sign snaps to its own street within this distance
SNAP_ANY_STREET_M = 18    # ...or to the nearest street of any name within this
POLE_M = 2.0              # signs closer than this along the kerb are one pole
MAX_ZONE_M = 150          # a rule with no closing sign stops after this
BLOCK_END_TRIM_M = 6      # stop short of the intersection centre
KERB_INSET_M = 1.0        # signs stand on the footpath; the kerb is about a metre closer
MIN_PIECE_M = 6           # drop slivers shorter than this after removing painted overlap
PAINT_COVER_M = 4.0       # a sign zone sample this close to paint is already drawn


@dataclass
class Chain:
    street: str
    poly: Polyline


@dataclass
class Sign:
    props: dict
    x: float
    y: float
    kind: str
    category: str
    direction: str
    chain: int = -1
    station: float = 0.0
    offset: float = 0.0
    rule: tuple | None = None


@dataclass
class Pole:
    station: float
    offset: float
    signs: list = field(default_factory=list)


def build_chains(road_features: list[dict]) -> list[Chain]:
    pieces = []
    for f in road_features:
        street = norm(f["properties"].get("STREET")).upper()
        for part in line_parts(f.get("geometry")):
            pts = []
            for c in part:
                p = to_xy(c[0], c[1])
                if not pts or math.dist(p, pts[-1]) > 0.01:
                    pts.append(p)
            if len(pts) >= 2:
                pieces.append((street, pts))

    def key(p):
        return round(p[0] * 2), round(p[1] * 2)

    ends = defaultdict(list)
    for i, (_, pts) in enumerate(pieces):
        ends[key(pts[0])].append(i)
        ends[key(pts[-1])].append(i)

    used = [False] * len(pieces)
    chains = []
    for i, (street, first) in enumerate(pieces):
        if used[i]:
            continue
        used[i] = True
        pts = list(first)
        for forward in (True, False):
            while True:
                node = key(pts[-1] if forward else pts[0])
                touching = ends[node]
                if len(touching) != 2:
                    break  # an intersection or a dead end: the block stops here
                others = [j for j in touching if not used[j]]
                if len(others) != 1 or pieces[others[0]][0] != street:
                    break
                j = others[0]
                used[j] = True
                q = pieces[j][1]
                if forward:
                    q = q if key(q[0]) == node else q[::-1]
                    pts.extend(q[1:])
                else:
                    q = q if key(q[-1]) == node else q[::-1]
                    pts[:0] = q[:-1]
        chains.append(Chain(street, Polyline(pts)))
    return chains


def snap_signs(sign_features: list[dict], chains: list[Chain]) -> tuple[list[Sign], list[Sign]]:
    index = SegmentIndex(cell=30)
    for i, ch in enumerate(chains):
        index.add_line(ch.poly.pts, i)

    snapped, loose = [], []
    for f in sign_features:
        geom = f.get("geometry")
        if not geom:
            continue
        p = f["properties"]
        x, y = to_xy(*geom["coordinates"][:2])
        sign = Sign(p, x, y, norm(p.get("PARKINGRESTRICTIONTYPE")), norm(p.get("SIGNCATEGORY")),
                    norm(p.get("SIGNDIRECTION")))
        sign.rule = sign_rule(sign.kind, sign.category)
        if not ends_zones(sign.kind, sign.category):
            continue
        street = norm(p.get("STREET")).upper()
        best_same, best_any = None, None
        for d, ci in index.near(x, y, SNAP_SAME_STREET_M):
            if chains[ci].street == street and (best_same is None or d < best_same[0]):
                best_same = (d, ci)
            if d <= SNAP_ANY_STREET_M and (best_any is None or d < best_any[0]):
                best_any = (d, ci)
        best = best_same or best_any
        if best is None:
            loose.append(sign)
            continue
        sign.chain = best[1]
        sign.station, sign.offset, _ = chains[best[1]].poly.project(x, y)
        snapped.append(sign)
    return snapped, loose


def arrow_dirs(sign: Sign, convention: int) -> list[int]:
    """Directions along the centreline (+1 / -1) that the sign's rule runs."""
    side = 1 if sign.offset > 0 else -1
    right = side * convention
    if sign.direction == "Right":
        return [right]
    if sign.direction == "Left":
        return [-right]
    if sign.direction == "Bi-Directional":
        return [1, -1]
    return []


def validate_convention(signs: list[Sign], convention: int = 1) -> dict:
    """Check the arrow convention using pairs of matching signs.

    A signed zone is bounded by two signs of the same type whose arrows point at
    each other. So with the right convention, consecutive same-type signs on one
    kerb should mostly face each other; with the wrong one, mostly face apart.
    (Painted lines are a noisier check: yellow lines often sit just outside a
    signed zone, at the corner.)
    """
    by_kerb = defaultdict(list)
    for s in signs:
        if s.direction in ("Left", "Right"):
            by_kerb[(s.chain, 1 if s.offset > 0 else -1)].append(s)
    facing = apart = 0
    for items in by_kerb.values():
        items.sort(key=lambda s: s.station)
        for a, b in zip(items, items[1:]):
            if a.kind != b.kind or not (3 <= b.station - a.station <= 120):
                continue
            (da,), (db,) = arrow_dirs(a, convention), arrow_dirs(b, convention)
            if da == 1 and db == -1:
                facing += 1
            elif da == -1 and db == 1:
                apart += 1
    total = facing + apart
    return {"pairs_facing": facing, "pairs_apart": apart,
            "agreement": round(facing / total, 3) if total else None}


def group_poles(signs: list[Sign]) -> dict[tuple[int, int], list[Pole]]:
    by_kerb = defaultdict(list)
    for s in signs:
        by_kerb[(s.chain, 1 if s.offset > 0 else -1)].append(s)
    poles = {}
    for k, items in by_kerb.items():
        items.sort(key=lambda s: s.station)
        groups: list[Pole] = []
        for s in items:
            if groups and s.station - groups[-1].station <= POLE_M:
                groups[-1].signs.append(s)
            else:
                groups.append(Pole(s.station, abs(s.offset), [s]))
        for g in groups:
            g.station = sum(s.station for s in g.signs) / len(g.signs)
            g.offset = sum(abs(s.offset) for s in g.signs) / len(g.signs)
        poles[k] = groups
    return poles


def sign_schedule(sign: Sign, pole: Pole):
    """Return (encoded schedule or None for always, hours text, unclear flag)."""
    text = norm(sign.props.get("PARKINGRESTRICTIONDAYSANDTIMES"))
    parsed = hours.parse(text) if text else None
    if parsed is None:
        if "Specified Times" in sign.kind or text:
            return None, text, True  # timed rule we can't read: show it always, flag it
        return None, "", False  # 'Any Time' style rule
    if parsed == hours.ALWAYS:
        return None, text, False
    if parsed == hours.OTHER_TIMES:
        others = []
        for o in pole.signs:
            if o is sign:
                continue
            t = norm(o.props.get("PARKINGRESTRICTIONDAYSANDTIMES"))
            op = hours.parse(t) if t else None
            if isinstance(op, list):
                others.append(op)
        if not others:
            return None, "All other times (see sign)", True
        sched = hours.complement(others)
        return hours.encode(sched), "Outside the other times on this sign", False
    return hours.encode(parsed), text, False


def build_zones(signs: list[Sign], chains: list[Chain], convention: int) -> list[dict]:
    """Return raw zones: dicts with chain, side, s0, s1, offset and rule details."""
    zones = []
    for (ci, side), poles in group_poles(signs).items():
        length = chains[ci].poly.length
        for k, pole in enumerate(poles):
            for sign in pole.signs:
                if not sign.rule:
                    continue
                layer, label, fine = sign.rule
                sched, hours_text, unclear = sign_schedule(sign, pole)
                for d in arrow_dirs(sign, convention):
                    if d > 0:
                        end = poles[k + 1].station if k + 1 < len(poles) else length - BLOCK_END_TRIM_M
                        s0, s1 = pole.station, end
                    else:
                        start = poles[k - 1].station if k > 0 else BLOCK_END_TRIM_M
                        s0, s1 = start, pole.station
                    open_ended = False
                    if s1 - s0 > MAX_ZONE_M:
                        open_ended = True
                        s0, s1 = (pole.station, pole.station + MAX_ZONE_M) if d > 0 else (pole.station - MAX_ZONE_M, pole.station)
                    if s1 - s0 < 1:
                        continue
                    zones.append({
                        "chain": ci, "side": side, "s0": s0, "s1": s1,
                        "offset": side * max(pole.offset - KERB_INSET_M, 2.5),
                        "layer": layer, "label": label, "fine": fine,
                        "sched": sched, "hours": hours_text, "unclear": unclear,
                        "open": open_ended,
                        "street": chains[ci].street.title(),
                    })
    return merge_zones(zones)


def merge_zones(zones: list[dict]) -> list[dict]:
    """Repeater signs make overlapping copies of the same rule: union them."""
    groups = defaultdict(list)
    for z in zones:
        key = (z["chain"], z["side"], z["layer"], z["label"], z["sched"], z["unclear"])
        groups[key].append(z)
    merged = []
    for items in groups.values():
        items.sort(key=lambda z: z["s0"])
        cur = dict(items[0])
        for z in items[1:]:
            if z["s0"] <= cur["s1"] + 1.0:
                cur["s1"] = max(cur["s1"], z["s1"])
                cur["open"] = cur["open"] and z["open"]
            else:
                merged.append(cur)
                cur = dict(z)
        merged.append(cur)
    return merged


def zone_geometries(zone: dict, chains: list[Chain], painted: SegmentIndex | None) -> list[list[list[float]]]:
    """Kerb-offset line(s) for a zone, with stretches already painted removed."""
    poly = chains[zone["chain"]].poly
    pts = poly.offset_points(zone["s0"], zone["s1"], zone["offset"], step=2.0)
    keep = [not (painted and painted.covered(x, y, PAINT_COVER_M)) for x, y in pts]
    pieces, run = [], []
    for p, k in zip(pts, keep):
        if k:
            run.append(p)
        else:
            if run:
                pieces.append(run)
            run = []
    if run:
        pieces.append(run)
    out = []
    for piece in pieces:
        length = sum(math.dist(a, b) for a, b in zip(piece, piece[1:]))
        if length >= MIN_PIECE_M:
            out.append([list(to_lonlat(x, y)) for x, y in simplify(piece)])
    return out
