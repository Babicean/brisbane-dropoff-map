# Brisbane Drop-off Map

A map for rideshare drivers showing where you can and can't stop to drop off a passenger in inner Brisbane, right now. Built from Brisbane City Council open data, then checked and corrected by drivers.

**Live map: https://babicean.github.io/brisbane-dropoff-map/** (beta)

Every judgement call is recorded in [docs/decisions.md](docs/decisions.md) so it can be audited or reversed.

## Why this exists

Brisbane City Council fines for stopping in the wrong place are expensive and increasingly automatic:

- Stopping in a no stopping zone or on a yellow line is **$345** (2 penalty units at $172.70, from 1 July 2026). A clearway is $518.
- Council runs fixed parking cameras at 40+ sites, but **mobile enforcement vehicles issue far more fines** (roughly 100,000 of about 176,000 in 2026 so far, against about 8,000 from fixed cameras).

So the useful question isn't "is there a camera here?" It's "is this bit of kerb legal right now, and if not, where's the nearest bit that is?"

## What the map does

The default **simple view** answers one question: where can I stop right now?

| Feature | What drivers see |
|---|---|
| **Bright green** (dots when zoomed out) | A 2-minute passenger drop-off is legal now: loading zones that allow passengers, passenger loading zones, No Parking zones |
| **Faint red** | Don't stop: every rule in force (no stopping, yellow lines, bus/taxi/mail zones, accessible bays, commercial-only loading zones, clearways in force, and anything unclear). Gets stronger as you zoom in |
| **Camera pin** | A street with a council parking camera; tap it to shade the street |
| **Time chip** | Shows rules for now (Brisbane time); tap to check another day and time |
| **Find a drop-off spot** | Search a venue, tap the map or use "Near me": the 3 nearest legal drop-off spots in force, with rough walking distance |
| **Report** | Writes a message (camera, fine, wrong map, good spot) with the location for the drivers group |
| **Tap any line** | Rule, street, hours, whether it's in force, fine amount, and whether it came from paint or signs |

**Show all rule types** (switch in the key) brings back the full colour coding: strong red, purple dashed clearways, amber "unclear: check the signs", grey dashes for timed rules not in force, and blue shading on camera streets.

Also: follows the phone's dark mode, can be added to the home screen, and keeps working with the last-loaded data when there's no signal.

## Scope

**Live (v2):** Brisbane City, Fortitude Valley, Newstead, Teneriffe, New Farm, Spring Hill, Herston.
South Bank is excluded automatically, because it sits in the South Brisbane suburb rather than Brisbane City.

**Later candidates:** South Brisbane (Graham Street is one of council's two busiest camera sites), Bowen Hills, Kangaroo Point, Milton.

Scope is a list of suburb names in `config/scope.json`; `"live"` picks the version the published map uses. Adding a suburb is a config change.

## Road rules behind the colours (Queensland)

| Restriction | Rule for a rideshare drop-off | Fine |
|---|---|---|
| No Stopping sign or yellow line | Can't stop at all, even for a moment | $345 |
| Clearway | Can't stop during signed hours (all times if none shown). Tow-away | $518 |
| Bus zone | Can't stop | $345 |
| Taxi zone / rank | Can't stop. Rideshare isn't a taxi | $345 |
| Loading zone | Up to 2 minutes to drop off or pick up passengers, unless signed otherwise | $172 if longer |
| Commercial vehicle loading zone | Permit holders only | $172 |
| No Parking | Up to 2 minutes for passengers, staying within 3 m of the car | $172 if longer |
| Accessible bay | Can't stop without a permit | $690 |
| Near an intersection | No stopping within 10 m (20 m at traffic lights) unless a sign permits it. **Not drawn yet** | $345 |

Sources: Brisbane City Council parking fines page (penalty unit $172.70 from 1 July 2026); *Transport Operations (Road Use Management—Road Rules) Regulation 2009* (Qld). This is a summary, not legal advice. **The signs on the street always override the map.**

## How it works

### Data sources

All from Brisbane City Council's open data, served as ArcGIS feature layers at
`https://services2.arcgis.com/dEKgZETqwmDAh1rP/ArcGIS/rest/services/<LAYER>/FeatureServer/0`:

| Layer | Geometry | Used for |
|---|---|---|
| `Parking_Line_locations` | Line | Painted kerb markings: the most reliable red and green |
| `Parking_Sign_locations` | Point | Every parking sign: type, arrow direction, hours |
| `Parking_Clearways` | Line | Clearways and their hours |
| `BCC_SDRN_roads` | Line | Road centrelines, to run sign rules along the kerb |
| `suburb_boundaries` | Polygon | Scope filter |

Layers return at most 2,000 records per request (`fetch.py` pages through them and checks each count against the server's own count). Some are stored in EPSG:28356; everything is requested as lat/long.

### Painted lines

Only `In Service` lines are drawn (`Disposal Complete` lines have been removed from the road). Text fields carry stray spaces, so they're normalised first. Yellow kerb lines are coded `No Stopping`; `Continuous Edge Line` is always a white lane edge and isn't drawn. A painted loading zone takes its type and hours from the nearest loading zone sign within 25 m. The full mapping is in [`pipeline/rules.py`](pipeline/rules.py).

### Signs into kerb zones

Many restrictions have a sign but no paint. [`pipeline/zones.py`](pipeline/zones.py):

1. Joins council's road centreline pieces into blocks.
2. Snaps each sign to its own street's centreline and notes which side it's on.
3. Turns the arrow into a direction: you read a sign standing on the road facing the kerb, so "Right" runs with the centreline's drawing direction on its left-hand side, and against it on the right-hand side.
4. Runs the rule from the sign to the next sign on that kerb, or to 6 m short of the corner (150 m at most).

The arrow convention is checked on every build: consecutive matching signs on one kerb should point at each other. Currently 91% do (1,799 vs 182); the build refuses to publish below 80%.

### Hours

[`pipeline/hours.py`](pipeline/hours.py) reads council's many hours formats (`MON-FRI:7am-9am`, `:7-9:30am ,MON-FRI:3:30-7pm`, `7AM-9AM 4PM-7PM MON-FRI`, `DAILY:MIDNIGHT-5:30 AM` …) into weekly schedules. "ALL OTHER TIMES" becomes everything outside the other panels on the same pole. The map evaluates schedules in Brisbane time. Unit tests: `tests/test_hours.py`.

### Cameras

[`config/cameras.json`](config/cameras.json) lists every publicly named fixed parking camera street. Council hasn't published its full list of 40+ sites; driver reports fill the gaps. Status is `announced` (street only), `reported` or `confirmed` (with coordinates).

## Running it

Needs Python 3.11+. No packages to install.

```bash
python pipeline/fetch.py                               # live scope into data/raw/
python pipeline/build.py                               # classify into web/data/
python pipeline/summarise.py --out docs/data-summary.md
python -m unittest discover tests                      # hours parser tests
python -m http.server -d web 8000                      # preview at http://localhost:8000
```

`build.py` exits with an error (and writes nothing) if the arrow check fails or a layer comes back suspiciously small.

### Publishing

- **Every push to `main` that touches `web/`** deploys to GitHub Pages (`.github/workflows/pages.yml`), usually within a minute.
- **Monthly**, `.github/workflows/refresh.yml` fetches fresh council data, runs the tests and build, and commits and deploys if the map layers changed. It can also be run by hand from the Actions tab.
- **Backup:** the first public version is kept on branch `backup/v0.1.0-preview`.

## Driver reports and fixes

1. A driver taps **Report**, puts the red cross on the spot (or uses their location), picks a type, and sends the message to the group with a photo of the sign.
2. Brendon checks it. A fix needs a photo of the sign or two independent reports.
3. Fixes go into config, then rebuild and push:
   - wrong red/green: add a `hide` entry to [`config/corrections.json`](config/corrections.json) (point + radius, optionally one layer)
   - something drivers should know: add a `note` entry (shows as an amber pin)
   - a camera: add or update it in `config/cameras.json` with coordinates and status

```json
{"corrections": [
  {"action": "hide", "lon": 153.03512, "lat": -27.45631, "radius_m": 15, "layer": "green", "reason": "Sign changed to No Stopping, photo 3 Nov"},
  {"action": "note", "lon": 153.03601, "lat": -27.45702, "text": "Mobile enforcement car parks here most Friday nights"}
]}
```

Never put number plates, names or fine numbers in these files: the repo is public. Nothing is stored by the website itself.

## Repo layout

```
config/          scope.json, layers.json, cameras.json, corrections.json
pipeline/        fetch.py, build.py, summarise.py, rules.py, zones.py, hours.py, geo.py
tests/           unit tests (python -m unittest discover tests)
data/raw/        untouched council downloads (gitignored)
docs/            decisions.md, data-summary.md (generated)
web/             the map page, icons, manifest, service worker
web/data/        processed GeoJSON the map loads (committed, so changes show up in diffs)
.github/         deploy and monthly refresh workflows
```

## Roadmap

- [x] **M1 Data:** fetch and summarise council layers
- [x] **v0 preview:** painted lines, loading zones, clearways; shareable page
- [x] **M2 Signs:** sign-only zones from arrow directions, with a convention check
- [x] **M3 Map:** time-aware rules, drop-off finder, fines in popups, night mode, home-screen app
- [x] **M4 Cameras:** announced streets, structure for reported/confirmed positions
- [x] **M5 Reports:** share-to-group reports; moderated corrections and notes
- [x] **v2:** Spring Hill and Herston; monthly automatic refresh
- [ ] **Corner rule:** draw the 10 m / 20 m no-stopping zones at intersections (needs council's traffic signal layer)
- [ ] **Fine heatmap** once enough fine reports are collected
- [ ] **Public holidays** for timed rules
- [ ] **Custom address**, e.g. map.babicean.com

## Known gaps

- The intersection rule (10 m from a corner, 20 m at lights) isn't drawn.
- Sign zones are inferred: a missing or misplaced sign record means a missing or wrong zone. Painted lines are more reliable than sign zones; popups say which a line came from.
- Driveways, bus stops without a zone sign, and anything else missing from council's data.
- Roads council doesn't manage are blank: hospital campuses (the internal roads at RBWH in Herston), private car parks and state-controlled roads' own signage where council has no record.
- Council's own notes say its parking data is indicative. Check signs.

## Attribution

Contains data © Brisbane City Council (open data, CC BY 4.0). Basemap © OpenStreetMap contributors via OpenFreeMap. Search by Photon (komoot), OpenStreetMap data.
Not affiliated with Brisbane City Council, Uber or DiDi.
