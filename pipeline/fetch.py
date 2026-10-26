#!/usr/bin/env python3
"""Fetch Brisbane City Council parking layers for the project scope.

Writes one GeoJSON file per layer (EPSG:4326) to data/raw/, plus the scope
suburb boundaries and a manifest.json recording counts and source dates.

Standard library only, so it runs on a fresh Python 3.11+ install.

Usage:
    python pipeline/fetch.py                     # v1 suburbs
    python pipeline/fetch.py --scope v2          # v1 + v2 suburbs
    python pipeline/fetch.py --only lines signs  # just some layers
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DEFAULT_OUT = ROOT / "data" / "raw"
PAGE_SIZE = 2000  # ArcGIS maxRecordCount for these layers
USER_AGENT = "brisbane-dropoff-map-pipeline/0.1"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def scope_suburbs(version: str) -> list[str]:
    """Versions are cumulative: v2 means every suburb in v1 and v2."""
    versions = load_json(CONFIG_DIR / "scope.json")["versions"]
    if version not in versions:
        sys.exit(f"Unknown scope {version!r}. Options: {', '.join(versions)}")
    suburbs: list[str] = []
    for name, names in versions.items():
        suburbs.extend(names)
        if name == version:
            break
    return suburbs


def arcgis(url: str, params: dict, retries: int = 3) -> dict:
    """POST a request to an ArcGIS REST endpoint and return parsed JSON.

    POST rather than GET because area filters send suburb polygons, which are
    too long for a URL.
    """
    body = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.load(resp)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            if attempt == retries:
                raise RuntimeError(f"Request to {url} failed: {exc}") from exc
            time.sleep(2**attempt)
            continue
        if isinstance(data, dict) and "error" in data:
            raise RuntimeError(f"ArcGIS error from {url}: {data['error']}")
        return data
    raise AssertionError("unreachable")


def sql_in(field: str, values: list[str]) -> str:
    quoted = ", ".join("'" + v.replace("'", "''") + "'" for v in values)
    return f"{field} IN ({quoted})"


def exceeded_limit(page: dict) -> bool:
    # ArcGIS puts this flag at the top level for f=json and under
    # "properties" for f=geojson.
    return bool(
        page.get("exceededTransferLimit")
        or page.get("properties", {}).get("exceededTransferLimit")
    )


def query_all(layer_url: str, params: dict, page_size: int) -> list[dict]:
    """Page through a query until ArcGIS stops returning features."""
    features: list[dict] = []
    offset = 0
    while True:
        page = arcgis(
            f"{layer_url}/query",
            {**params, "resultOffset": offset, "resultRecordCount": page_size},
        )
        batch = page.get("features", [])
        features.extend(batch)
        if not batch:
            break
        if not exceeded_limit(page) and len(batch) < page_size:
            break
        offset += len(batch)
    return features


def last_edit(meta: dict) -> str | None:
    ms = (meta.get("editingInfo") or {}).get("dataLastEditDate")
    if not ms:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date().isoformat()


def fetch_boundaries(base_url: str, cfg: dict, suburbs: list[str]) -> tuple[dict, dict]:
    """Return (esri polygon for area filters, GeoJSON FeatureCollection)."""
    layer_url = f"{base_url}/{cfg['service']}/FeatureServer/0"
    where = sql_in(cfg["name_field"], suburbs)

    esri = arcgis(
        f"{layer_url}/query",
        {"where": where, "outFields": cfg["name_field"], "outSR": 4326, "f": "json"},
    )
    found = {f["attributes"][cfg["name_field"]] for f in esri["features"]}
    missing = sorted(set(suburbs) - found)
    if missing:
        sys.exit(f"Suburb names not found in council boundaries: {missing}")

    rings = [ring for f in esri["features"] for ring in f["geometry"]["rings"]]
    area = {"rings": rings, "spatialReference": {"wkid": 4326}}

    geojson = arcgis(
        f"{layer_url}/query",
        {"where": where, "outFields": cfg["name_field"], "outSR": 4326, "f": "geojson"},
    )
    return area, geojson


def fetch_layer(base_url: str, cfg: dict, suburbs: list[str], area: dict) -> tuple[dict, dict]:
    layer_url = f"{base_url}/{cfg['service']}/FeatureServer/0"
    meta = arcgis(layer_url, {"f": "json"})
    oid = meta.get("objectIdField") or "OBJECTID"
    page_size = min(PAGE_SIZE, meta.get("maxRecordCount") or PAGE_SIZE)

    if cfg["filter"] == "suburb":
        params = {"where": sql_in(cfg["suburb_field"], suburbs)}
    elif cfg["filter"] == "area":
        params = {
            "where": "1=1",
            "geometry": json.dumps(area),
            "geometryType": "esriGeometryPolygon",
            "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects",
        }
    else:
        raise ValueError(f"Unknown filter type {cfg['filter']!r}")

    features = query_all(
        layer_url,
        {**params, "outFields": "*", "outSR": 4326, "orderByFields": oid, "f": "geojson"},
        page_size,
    )

    # Independent count from the server, so a silent paging bug shows up.
    server_count = arcgis(
        f"{layer_url}/query", {**params, "returnCountOnly": "true", "f": "json"}
    ).get("count")

    info = {
        "service": cfg["service"],
        "url": layer_url,
        "filter": cfg["filter"],
        "features": len(features),
        "server_count": server_count,
        "data_last_edit": last_edit(meta),
    }
    return {"type": "FeatureCollection", "features": features}, info


def write_geojson(path: Path, collection: dict) -> None:
    path.write_text(json.dumps(collection, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    layers_cfg = load_json(CONFIG_DIR / "layers.json")
    layer_names = list(layers_cfg["layers"])

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--scope", default="v1", help="scope version from config/scope.json (default v1)")
    parser.add_argument("--only", nargs="+", choices=layer_names, help="fetch only these layers")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output folder (default data/raw)")
    args = parser.parse_args()

    suburbs = scope_suburbs(args.scope)
    base_url = layers_cfg["base_url"]
    args.out.mkdir(parents=True, exist_ok=True)

    print(f"Scope {args.scope}: {', '.join(suburbs)}")
    area, boundaries = fetch_boundaries(base_url, layers_cfg["boundaries"], suburbs)
    write_geojson(args.out / "suburbs.geojson", boundaries)

    manifest = {
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope": args.scope,
        "suburbs": suburbs,
        "layers": {},
    }
    problems = []
    for name in args.only or layer_names:
        print(f"  {name:<20}", end="", flush=True)
        collection, info = fetch_layer(base_url, layers_cfg["layers"][name], suburbs, area)
        info["file"] = f"{name}.geojson"
        write_geojson(args.out / info["file"], collection)
        manifest["layers"][name] = info
        flag = ""
        if info["server_count"] is not None and info["server_count"] != info["features"]:
            flag = f"  MISMATCH: server says {info['server_count']}"
            problems.append(name)
        print(f"{info['features']:>6} features  (council data edited {info['data_last_edit']}){flag}")

    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote {len(manifest['layers'])} layers to {args.out}")
    if problems:
        print(f"Count mismatch on: {', '.join(problems)}. Re-run before using this data.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
