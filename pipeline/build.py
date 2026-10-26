#!/usr/bin/env python3
"""Turn the raw council layers into the GeoJSON files the map loads.

Reads data/raw/ (from fetch.py) and config/, writes web/data/:
    red.geojson        don't stop: painted lines and sign zones
    green.geojson      2-minute passenger drop-off is legal
    review.geojson     unclear: check the signs
    clearways.geojson  clearways with their hours
    points.geojson     signs we couldn't place on a street, and moderated notes
    cameras.geojson    parking camera streets and known camera positions
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
from geo import (SegmentIndex, line_parts, point_in_rings, point_segment_distance,  # noqa: E402
                 polygon_rings, to_lonlat, to_xy)
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

def painted_layers(lines, snapped_signs, poles_by_sign):
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
            best = None
            for s in loading_signs:
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
            sched, hours_text, unclear = zones.sign_schedule(sign, poles_by_sign[id(sign)])
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
        title = {"announced": "Council parking camera on this street",
                 "reported": "Parking camera reported by a driver",
                 "confirmed": "Parking camera"}[status]
        props = dict(label=title, street=cam["street"].title(), status=status, source=cam.get("source"),
                     fine="Cameras catch any stop in no stopping, bus, taxi and loading zones, clearways and yellow lines")
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

    red, green, review, skipped = painted_layers(load("lines"), snapped, poles_by_sign)
    painted_red, painted_any = index_lines(red), index_lines(red + green + review)

    zone_stats = Counter()
    for z in zones.build_zones(snapped, chains, convention=1):
        cover = painted_red if z["layer"] == "red" else painted_any
        geoms = zones.zone_geometries(z, chains, cover)
        target = {"red": red, "green": green, "review": review}[z["layer"]]
        for coords in geoms:
            target.append(feature("LineString", coords,
                                  label=label_with_flags(z["label"], z["unclear"], z["open"]),
                                  street=z["street"], fine=FINES.get(z["fine"]) if z["fine"] else None,
                                  hours=z["hours"], sched=z["sched"], src="sign"))
            zone_stats[z["layer"]] += 1

    points = []
    for s in loose:
        if s.rule:
            layer, label, fine = s.rule
            points.append(feature("Point", list(to_lonlat(s.x, s.y)), layer=layer,
                                  label=f"{label} (sign; couldn't place on a street)",
                                  street=norm(s.props.get("STREET")).title(), arrow=s.direction))

    clearways, clearway_parse = clearway_layer(load("clearways"))
    cameras, cameras_placed, cameras_missing = camera_layer(chains, suburbs_geojson, set(manifest["suburbs"]))
    layers = {"red": red, "green": green, "review": review, "clearways": clearways}
    hidden = apply_corrections(layers, points)

    for name, minimum in MIN_FEATURES.items():
        if len(layers[name]) < minimum:
            print(f"Only {len(layers[name])} {name} features (expected at least {minimum}). "
                  "Not writing: the council download looks incomplete.", file=sys.stderr)
            return 1

    outputs = {**layers, "points": points, "cameras": cameras}
    for name, feats in outputs.items():
        (OUT / f"{name}.geojson").write_text(
            json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8")

    meta = {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fetched_at": manifest["fetched_at"],
        "scope": manifest["scope"],
        "suburbs": [s.title() for s in manifest["suburbs"]],
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
            "features_hidden_by_corrections": hidden,
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
