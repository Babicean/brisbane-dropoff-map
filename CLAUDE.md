# CLAUDE.md

Context for Claude Code sessions in this repo. README.md has the full picture; this is the short version plus conventions.

## What this is

A web map for Brisbane rideshare drivers: red where you can't stop, green where a 2-minute passenger drop-off is legal, evaluated for the current Brisbane time. Data comes from Brisbane City Council's ArcGIS open data layers, corrected by moderated driver reports. Live at https://babicean.github.io/brisbane-dropoff-map/ (GitHub Pages from `web/`).

## Working agreement

- Brendon has delegated routine decisions: make the call, don't ask. **Record every judgement call in `docs/decisions.md`** (next number, what/why/how to change; mark real-world guesses as **Assumption**).
- Wrong green is the worst error (a driver stops and gets fined); wrong red is next. When unsure, use review (amber), never green.

## Commands

```bash
python pipeline/fetch.py                               # live scope -> data/raw/
python pipeline/build.py                               # -> web/data/ (exits non-zero on a failed quality check)
python pipeline/summarise.py --out docs/data-summary.md
python -m unittest discover tests
python -m http.server -d web 8000
python tools/check_map.py http://localhost:8000/ out/   # browser smoke test (needs Playwright)
```

Pushing `web/` changes to `main` deploys. The monthly refresh workflow does fetch → build → commit → deploy on its own.

## Where things live

- `config/scope.json` suburbs per version, `"live"` picks the published one. `config/layers.json` council layers. `config/cameras.json`, `config/corrections.json` moderated driver input. `config/areas.json` area tabs (suburb grouping, map names), `config/landmarks.json` landmarks; built into `web/data/areas.geojson` by `areas_layer()` (D039).
- `pipeline/rules.py` **every** red/green/review decision and fine amount. Don't scatter type checks elsewhere.
- `pipeline/zones.py` signs → kerb zones (arrow convention, extents). `pipeline/hours.py` hours text → weekly schedules (`mask,start,end`, Monday = bit 0, minutes, Brisbane time). `pipeline/geo.py` local-metre geometry.
- `web/index.html` the whole client (MapLibre 5.24.0 pinned, OpenFreeMap basemap, Photon search). Two views: **simple** (default: bright green + one faint "don't stop" red, D037) and **detail** (all rule colours), switched by `applyMode()`. Keep the simple view calm: new information goes in popups or the detail view first. Area tabs in the header (lit tab = area at the map centre, `#area-id` link); suburb names and landmarks draw above the kerb lines, borders (off by default) below the green; an invisible `pin-space` symbol layer keeps labels out from under the camera pins (DOM markers). `web/sw.js` network-first offline cache; bump `CACHE` if the shell changes.

## Conventions

- Python 3.11+, standard library only for the pipeline. Read/write files with `encoding="utf-8"` (Windows default isn't UTF-8).
- All GeoJSON the site loads is EPSG:4326; request `outSR=4326` from ArcGIS.
- `data/raw/` is gitignored. Processed `web/data/` is committed so data changes show in diffs.
- Unknown restriction types go to review, never silently to red or green.
- Timed features carry `sched`; anything with unreadable hours is drawn always-on with "hours unclear".

## Council data gotchas

- Draw only `ASSETLIFECYCLE == "In Service"` lines. `Disposal Complete` lines are gone from the road.
- Normalise whitespace before matching text (`'Loading Zone '`).
- Yellow kerb lines are `PARKINGRESTRICTIONTYPE = "No Stopping"`; `Continuous Edge Line` is a white lane edge.
- Sign `SIGNDIRECTION` is read from the road facing the kerb (see `zones.py`); `validate_convention` must stay ≥ 80% or the build stops.
- Multi-panel signs share a pole: "ALL OTHER TIMES" = complement of the other panels on that pole.
- Clearway `OPERATIONAL_TIME` is free text; blank means all times.
- `BCC_Camera_Locations_view` is flood cameras, not parking cameras.
- OpenStreetMap Overpass servers weren't reachable from the cloud build environment; council's `BCC_SDRN_roads` is used for centrelines instead.

## Rules for report data

- Never store or publish number plates, names or infringement notice numbers (the repo is public).
- Nothing from a report reaches the map without moderation (a sign photo or two independent reports).
- The website stores nothing; reports go to the drivers group via the share sheet.

## Don't

- Don't present the map as authoritative. The bottom notice must say signs override it.
- Don't add businesses or POIs to the basemap. Landmarks in `config/landmarks.json` are a short list of orientation points, not businesses.
- Don't commit `data/raw/`.
