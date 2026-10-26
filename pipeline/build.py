#!/usr/bin/env python3
"""Turn the raw council layers into the small GeoJSON files the map loads.

Reads data/raw/ (from fetch.py) and writes web/data/:
    red.geojson        painted kerb you can't stop on
    green.geojson      painted loading zones where a 2-minute passenger drop-off is legal
    green_signs.geojson  passenger loading zones that only have a sign, no paint
    review.geojson     anything the rules below don't cover, shown as "check the signs"
    clearways.geojson  clearways with their hours as council wrote them
    meta.json          data dates and counts for the page footer

v0 scope: painted lines plus loading zone signs. Sign-only No Stopping zones
(no paint) and clearway hour parsing come next.

Standard library only.
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "web" / "data"

# --- Classification tables: the only place red/green decisions live -------

# Painted line PARKINGRESTRICTIONTYPE (whitespace-normalised) -> map label.
RED_LINES = {
    "No Stopping": "No stopping",
    "Bus Bay": "Bus zone",
    "Taxi Rank": "Taxi rank (taxis only)",
    "Mail Zone": "Mail zone",
    "Accessible Parking": "Accessible bay (permit only)",
}
LOADING_LINE = "Loading Zone"  # colour decided by the nearest loading zone sign
NOT_DRAWN_LINES = {
    "Parking - Parallel",
    "Parking - Angle",
    "Motorcycle Parking",
}
# ("Not Applicable", subtype) pairs: white lane edge lines aren't restrictions.
NOT_DRAWN_SUBTYPES = {"Continuous Edge Line"}

# Loading zone sign PARKINGRESTRICTIONTYPE -> (layer, label).
LOADING_SIGNS = {
    "Loading Zone - Passenger 2 Min. Max, Commercial Vehicles 20 Min. Max": ("green", "Loading zone: passengers 2 min"),
    "Loading Zone Passengers 2 Min. Max": ("green", "Passenger loading zone: 2 min"),
    "Loading Zone": ("green", "Loading zone: passengers 2 min"),
    "Loading Zone Commercial Vehicle 20 Min. Max": ("red", "Commercial vehicle loading zone"),
    "Works Zone (Construction Vehicles)": ("red", "Works zone (construction vehicles)"),
}

SIGN_MATCH_METRES = 25  # a painted loading zone takes its type from a sign this close
COORD_DP = 6            # ~0.1 m; keeps files small


# --- Helpers ----------------------------------------------------------------

def norm(value) -> str:
    return " ".join(str(value).split()) if value is not None else ""


def load(name: str) -> list[dict]:
    path = RAW / f"{name}.geojson"
    if not path.exists():
        sys.exit(f"Missing {path}. Run pipeline/fetch.py first.")
    return json.loads(path.read_text(encoding="utf-8"))["features"]


def round_coords(coords):
    if isinstance(coords[0], (int, float)):
        return [round(coords[0], COORD_DP), round(coords[1], COORD_DP)]
    return [round_coords(c) for c in coords]


def feature(geometry: dict, **props) -> dict:
    geom = {"type": geometry["type"], "coordinates": round_coords(geometry["coordinates"])}
    return {"type": "Feature", "geometry": geom, "properties": {k: v for k, v in props.items() if v}}


def title_street(street) -> str:
    return norm(street).title()


# Local flat projection in metres. Fine at suburb scale near Brisbane.
LAT0 = math.radians(-27.46)
M_PER_DEG_LAT = 110_574
M_PER_DEG_LON = 111_320 * math.cos(LAT0)


def to_xy(lon: float, lat: float) -> tuple[float, float]:
    return lon * M_PER_DEG_LON, lat * M_PER_DEG_LAT


def line_parts(geometry: dict) -> list[list[list[float]]]:
    if geometry["type"] == "LineString":
        return [geometry["coordinates"]]
    if geometry["type"] == "MultiLineString":
        return geometry["coordinates"]
    return []


def point_to_line_metres(px: float, py: float, geometry: dict) -> float:
    best = math.inf
    for part in line_parts(geometry):
        pts = [to_xy(*c[:2]) for c in part]
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            dx, dy = bx - ax, by - ay
            seg = dx * dx + dy * dy
            t = 0.0 if seg == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg))
            best = min(best, math.hypot(px - (ax + t * dx), py - (ay + t * dy)))
    return best


def collection(features: list[dict]) -> dict:
    return {"type": "FeatureCollection", "features": features}


def write(name: str, data) -> None:
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


# --- Build ------------------------------------------------------------------

def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((RAW / "manifest.json").read_text(encoding="utf-8"))

    lines = load("lines")
    signs = load("signs")
    clearways = load("clearways")

    red, green, review = [], [], []
    skipped = Counter()

    loading_signs = []
    for s in signs:
        kind = norm(s["properties"].get("PARKINGRESTRICTIONTYPE"))
        if kind in LOADING_SIGNS and s.get("geometry"):
            lon, lat = s["geometry"]["coordinates"][:2]
            loading_signs.append((to_xy(lon, lat), kind, s))

    matched_signs: set[int] = set()

    for f in lines:
        p = f["properties"]
        geom = f.get("geometry")
        if not geom:
            skipped["no geometry"] += 1
            continue
        lifecycle = norm(p.get("ASSETLIFECYCLE"))
        kind = norm(p.get("PARKINGRESTRICTIONTYPE"))
        subtype = norm(p.get("PAVEMENTMARKINGSUBTYPE"))
        street = title_street(p.get("STREET"))

        if lifecycle == "Disposal Complete":
            skipped["removed from road"] += 1
            continue
        if lifecycle != "In Service":
            name = subtype if kind in ("", "Not Applicable") else kind
            review.append(feature(geom, label=f"{name} (planned, may not be painted yet)", street=street))
            continue
        if kind in NOT_DRAWN_LINES or subtype in NOT_DRAWN_SUBTYPES:
            skipped["parking bay or lane edge"] += 1
            continue
        if kind in RED_LINES:
            red.append(feature(geom, label=RED_LINES[kind], street=street))
            continue
        if kind == LOADING_LINE:
            nearest = None
            for i, ((sx, sy), sign_kind, sign) in enumerate(loading_signs):
                d = point_to_line_metres(sx, sy, geom)
                if d <= SIGN_MATCH_METRES and (nearest is None or d < nearest[0]):
                    nearest = (d, i, sign_kind, sign)
            if nearest is None:
                review.append(feature(geom, label="Loading zone: type unknown, check the sign", street=street))
                continue
            _, idx, sign_kind, sign = nearest
            matched_signs.add(idx)
            layer, label = LOADING_SIGNS[sign_kind]
            hours = norm(sign["properties"].get("PARKINGRESTRICTIONDAYSANDTIMES"))
            target = green if layer == "green" else red
            target.append(feature(geom, label=label, street=street, hours=hours))
            continue
        name = subtype if kind in ("", "Not Applicable") else kind
        review.append(feature(geom, label=f"{name}: check the signs", street=street))

    # Green loading zone signs with no painted zone nearby: show as points.
    green_signs = []
    for i, ((sx, sy), sign_kind, sign) in enumerate(loading_signs):
        layer, label = LOADING_SIGNS[sign_kind]
        if layer != "green" or i in matched_signs:
            continue
        near_paint = any(
            point_to_line_metres(sx, sy, g["geometry"]) <= SIGN_MATCH_METRES for g in green
        )
        if near_paint:
            continue
        sp = sign["properties"]
        green_signs.append(
            feature(
                sign["geometry"],
                label=f"{label} (sign only, no paint)",
                street=title_street(sp.get("STREET")),
                hours=norm(sp.get("PARKINGRESTRICTIONDAYSANDTIMES")),
                arrow=norm(sp.get("SIGNDIRECTION")),
            )
        )

    clearway_features = [
        feature(
            c["geometry"],
            label="Clearway: no stopping during these hours",
            hours=norm(c["properties"].get("OPERATIONAL_TIME")) or "All times",
        )
        for c in clearways
        if c.get("geometry")
    ]

    outputs = {
        "red.geojson": red,
        "green.geojson": green,
        "green_signs.geojson": green_signs,
        "review.geojson": review,
        "clearways.geojson": clearway_features,
    }
    for name, feats in outputs.items():
        write(name, collection(feats))

    meta = {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fetched_at": manifest["fetched_at"],
        "scope": manifest["scope"],
        "suburbs": [s.title() for s in manifest["suburbs"]],
        "council_data_edited": {k: v["data_last_edit"] for k, v in manifest["layers"].items()},
        "counts": {k.removesuffix(".geojson"): len(v) for k, v in outputs.items()},
    }
    write("meta.json", meta)

    for name, feats in outputs.items():
        size = (OUT / name).stat().st_size / 1024
        print(f"  {name:<22}{len(feats):>6} features  {size:>7.0f} KB")
    print("  skipped:", dict(skipped))


if __name__ == "__main__":
    main()
