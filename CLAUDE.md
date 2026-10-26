# CLAUDE.md

Context for Claude Code sessions in this repo. README.md has the full picture; this is the short version plus conventions.

## What this is

A web map for Brisbane rideshare drivers: red where you can't stop, green where a 2-minute passenger drop-off is legal. Data comes from Brisbane City Council's ArcGIS open data layers, corrected by moderated driver reports.

## Scope

- v1 suburbs: Brisbane City, Fortitude Valley, Newstead, Teneriffe, New Farm
- v2 suburbs: Spring Hill, Herston
- Keep the suburb list in one config file. Filtering uses the `SUBURB` field on the lines layer; layers without that field get clipped by area.

## Conventions

- Python 3.11+ for the pipeline. `fetch.py` is standard library only; keep it that way. Later steps can add `shapely` if needed; add `geopandas` only if it clearly earns its place.
- Read and write files with `encoding="utf-8"`. The default on Windows is not UTF-8 and council text contains em dashes.
- Scope and layer definitions live in `config/scope.json` and `config/layers.json`. Don't hard-code suburb names or layer URLs in scripts.
- All GeoJSON the site loads is EPSG:4326. Request `outSR=4326` from ArcGIS rather than reprojecting locally.
- ArcGIS returns max 2,000 records per query: always paginate with `resultOffset` until `exceededTransferLimit` is false.
- `data/raw/` is gitignored. Only processed, scoped GeoJSON goes in `web/data/`.
- The red/green classification lives in one mapping table in code (see the README table). Don't scatter type checks across files.
- Unknown restriction types go to a `review` bucket, never silently to red or green.

## Council data gotchas (found in M1)

- Only draw lines with `ASSETLIFECYCLE == "In Service"`. `Disposal Complete` lines are gone from the road; `Preliminary` goes to review.
- Normalise whitespace before matching text fields: values like `'Loading Zone '` have trailing spaces.
- Yellow kerb lines are `PARKINGRESTRICTIONTYPE = "No Stopping"`. `Continuous Edge Line` is always white lane edge in scope; don't draw it.
- Use the sign layer for loading zone types. The two loading zone point layers are stale extracts of it.
- Clearway `OPERATIONAL_TIME` is free text in many formats; blank means all times.
- `BCC_Camera_Locations_view` is flood cameras, not parking cameras.

## Rules for report data

- Never store or publish number plates, names or infringement notice numbers.
- Fine reports only feed the heatmap; no individual pins.
- Nothing from a report reaches `web/data/` without moderation.

## Don't

- Don't present the map as authoritative. The footer must say signs on the street override it.
- Don't add businesses or POIs to the basemap.
