# Brisbane Drop-off Map

A map for rideshare drivers showing where you can and can't stop to drop off a passenger in inner Brisbane. Built from Brisbane City Council open data, then checked and corrected by drivers.

> **Status:** v0 preview live at **https://babicean.github.io/brisbane-dropoff-map/**. Painted lines, loading zones and clearways only; sign-only No Stopping zones are next.

## Why this exists

Brisbane City Council fines for stopping in the wrong place are expensive and increasingly automatic:

- Stopping in a no stopping zone or on a yellow line is **2 penalty units** (about $333 at the 2025–26 rate; penalty units are indexed every 1 July).
- Council runs fixed parking cameras at 40+ sites, but **mobile enforcement vehicles issue far more fines** (roughly 100,000 of about 176,000 in 2026 so far, against about 8,000 from fixed cameras).

So the useful question isn't "is there a camera here?" It's "is this bit of kerb legal, and if not, where's the nearest bit that is?" This map answers that before you arrive.

## What the map shows

| Layer | Meaning |
|---|---|
| **Red** | Don't stop: no stopping lines, yellow continuous edge lines, signed no stopping zones, clearways (only during their operating hours), bus zones, taxi zones and ranks, mail zones, accessible bays |
| **Green** | Legal for a quick passenger drop-off: passenger loading zones, standard loading zones, No Parking zones |
| **Camera markers** | Council's fixed parking camera sites |
| **Driver reports** | Moderated reports from the group: fine locations (heatmap), missing or wrong zones, camera sightings |

The base map shows streets and street names only. No businesses, reviews or points of interest.

## Scope

**v1:** Brisbane City, Fortitude Valley, Newstead, Teneriffe, New Farm.
South Bank is excluded automatically, because it sits in the South Brisbane suburb rather than Brisbane City.

**v2:** Spring Hill and Herston (the RBWH hospital precinct).

**Later candidates:** South Brisbane (Graham Street is one of council's two busiest camera sites), Bowen Hills, Kangaroo Point, Milton.

Scope is a list of suburb names in config. Each record in council's parking lines dataset carries a `SUBURB` field, so adding a suburb is a config change rather than new code.

## Road rules behind the colours (Queensland)

| Restriction | Rule for a rideshare drop-off | Penalty |
|---|---|---|
| No Stopping sign or yellow line | Can't stop at all, even for a moment | 2 PU |
| Clearway | Can't stop during signed hours (24/7 if no hours shown). Tow-away zone | 3 PU |
| Bus zone | Can't stop | 2 PU |
| Taxi zone / rank | Can't stop. Rideshare isn't a taxi | 2 PU |
| Loading zone | Up to 2 minutes to drop off or pick up passengers, unless signed otherwise | 1 PU if longer |
| Commercial vehicle loading zone | Permit holders only | 1 PU |
| No Parking | Up to 2 minutes to drop off or pick up passengers, staying within 3 m of the car | 1 PU |
| Accessible bay | Can't stop without a current permit | 4 PU |

Sources: Brisbane City Council parking fines page; *Transport Operations (Road Use Management—Road Rules) Regulation 2009* (Qld). This is a summary, not legal advice. **The signs on the street always override the map.** Council won't withdraw a fine because a sign was confusing.

## Data sources

All from Brisbane City Council's open data, served as ArcGIS feature layers:

`https://services2.arcgis.com/dEKgZETqwmDAh1rP/arcgis/rest/services/<LAYER>/FeatureServer/0`

| Layer | Geometry | Key fields | Last updated | Use |
|---|---|---|---|---|
| `Parking_Line_locations` | Line | `SUBURB`, `STREET`, `PARKINGRESTRICTIONTYPE`, `PAVEMENTMARKINGSUBTYPE`, `MARKINGCOLOUR`, `ASSETLIFECYCLE`, `PAVEMENTLINELENGTH` | 19 Oct 2026 | Main red/green layer |
| `Parking_Sign_locations` | Point | `SUBURB`, `STREET`, `SIGNCATEGORY`, `PARKINGRESTRICTIONTYPE`, `SIGNDIRECTION`, `PARKINGRESTRICTIONDAYSANDTIMES` | 19 Oct 2026 (first surveyed 2020–21) | Sign-only zones, loading zone types, time-based rules |
| `Parking_Clearways` | Line | `CATEGORY`, `OPERATIONAL_TIME` | 19 Oct 2026 | Time-aware red layer. No suburb field, so filtered by area |
| `Disability_permit_parking` | Point | `TYPE`, `OPERATING_TIMES`, `BAYS`, `STREET` | 17 Feb 2026 | Red. No suburb field, so filtered by area |
| `parking_two_minute_passenger_loading_zones` | Point | `Suburb`, `Street`, `Parking_Restriction_Type`, `ParkingRestrictionDaysandTimes` | 26 Aug 2024 | Cross-check only (see below) |
| `parking_commercial_vehicle_loading_zones` | Point | same as above | 26 Aug 2024 | Cross-check only (see below) |
| `suburb_boundaries` | Polygon | `SUBURB_NAME` | 20 Oct 2026 | Scope filter and clipping |

Technical notes:
- Layers support GeoJSON output and return at most **2,000 records per request**, so paginate with `resultOffset`.
- Some layers are stored in **EPSG:28356** (GDA94 / MGA zone 56). Request `outSR=4326` so the output is lat/long for the web map.
- Suburb names are upper case and match across layers (`BRISBANE CITY`, `FORTITUDE VALLEY`, …).
- The same datasets are mirrored on [data.brisbane.qld.gov.au](https://data.brisbane.qld.gov.au).

### What the first data pull showed (M1)

Full tallies are in [docs/data-summary.md](docs/data-summary.md). The things that change the design:

- **The red layer is mostly automatic.** About 52 km of in-service yellow No Stopping line across 1,816 segments in the v1 suburbs.
- **Filter out removed lines.** 144 line records are `Disposal Complete`, including 74 No Stopping lines that are no longer on the road. Only `In Service` lines get drawn. The 5 `Preliminary` lines go to review.
- **Yellow kerb lines are coded as No Stopping, not as edge lines.** Every `Continuous Edge Line` in scope is white, so none of them mean no stopping.
- **Text fields have stray spaces** (`'Loading Zone '`, `'Taxi Rank '`). Normalise whitespace before matching.
- **The sign data is better than expected.** It's maintained (last edited October 2026, every sign in service) and records arrow direction, so sign-only zones can be extended from each sign in the direction it points.
- **Use signs, not the two loading zone point layers.** Those two layers appear to be extracts of the sign records (same type names, same 357 mixed passenger/commercial zones), last updated August 2024, and they overlap each other.
- **Clearway hours are free text** in a dozen formats (`7AM-9AM  4PM-7PM MON-FRI`, `4PM-7PM M-F`, `AT ALL TIMES`). They need a parser. Blank means all times.
- **Council's `BCC_Camera_Locations_view` layer is flood cameras on creeks, not parking cameras.** There's no public layer of parking camera sites.

### How line types map to layers

Match on `PARKINGRESTRICTIONTYPE` (whitespace-normalised) and only for `ASSETLIFECYCLE = In Service`.

| `PARKINGRESTRICTIONTYPE` | Layer | Note |
|---|---|---|
| No Stopping | Red | All yellow. The main red layer |
| Bus Bay | Red | |
| Taxi Rank | Red | |
| Mail Zone | Red | |
| Accessible Parking | Red | Permit only |
| Loading Zone | Green | Confirm the zone type from the nearest loading zone sign (see below) |
| Special Purpose Zone | Review | Mostly CBD streets. Check what each one is reserved for |
| Not Applicable + Unspecified Zone (yellow) | Review | 6 segments |
| Not Applicable + Continuous Edge Line (white) | Not drawn | Lane edge, not a parking restriction |
| Parking - Parallel / Angle, Motorcycle Parking | Not drawn in v1 | |

### Loading zone signs

| Sign `PARKINGRESTRICTIONTYPE` | Layer | Why |
|---|---|---|
| Loading Zone - Passenger 2 Min. Max, Commercial Vehicles 20 Min. Max | Green | Passenger drop-off allowed for 2 minutes |
| Loading Zone Passengers 2 Min. Max | Green | Passenger loading zone |
| Loading Zone | Green | Standard loading zone: 2 minutes for passengers unless signed otherwise |
| Loading Zone Commercial Vehicle 20 Min. Max | Red | Commercial vehicles only. Check one of these signs on the street to confirm passengers aren't allowed |

## Fixed camera sites in v1 scope

Seeded from council's 2025 announcements. The network has since grown to 40+ sites, so this list is incomplete. Drivers fill the gaps.

| Street | Suburb | Status |
|---|---|---|
| McLachlan Street | Fortitude Valley | Announced (trial site) |
| Wickham Street | Fortitude Valley | Announced (trial site) |
| Symes Street | Fortitude Valley | Announced (trial site) |
| Robertson Street | Fortitude Valley | Announced |
| Festival Place | Newstead | Announced |
| Moray Street | New Farm | Announced |
| Charlotte Street | Brisbane City | Announced |

Each site has a "parking enforcement camera in use" sign. Exact camera positions get confirmed by driver reports. Council doesn't publish these as open data: its only camera layer (`BCC_Camera_Locations_view`) is flood monitoring cameras.

## Architecture

```
BCC ArcGIS layers ──► pipeline/fetch.py ──► data/raw/*.geojson (not committed)
                                                │
                                                ▼
                         pipeline/build.py: filter to scope suburbs,
                         classify red/green, clip clearways
                                                │
                                                ▼
                      web/data/*.geojson ──► web/ (MapLibre GL, installable web app)
                                                ▲                 │
Driver reports (form ─► sheet) ─► moderation ───┘                 ▼
                                                            GitHub Pages
```

- **Pipeline:** Python 3. Runs monthly, since council updates the lines data regularly.
- **Map:** MapLibre GL JS with a stripped-down vector basemap (roads and labels only). Installable to a phone home screen.
- **Reports:** Google Form feeding a Sheet to start. Move to a proper database only if volume justifies it.
- **Hosting:** GitHub Pages.

### Repo layout

```
config/          scope.json (suburbs per version), layers.json (council layers)
pipeline/        fetch.py, summarise.py, build.py
data/raw/        untouched council downloads (gitignored)
docs/            data-summary.md (generated), rule references, research notes
web/             the map page, deployed to GitHub Pages
web/data/        processed GeoJSON the map loads (committed, so changes show up in diffs)
.github/         Pages deploy workflow
```

## Running the pipeline

Needs Python 3.11+. No packages to install yet.

```bash
python pipeline/fetch.py                              # v1 suburbs into data/raw/
python pipeline/fetch.py --scope v2                   # v1 + Spring Hill + Herston
python pipeline/summarise.py --out docs/data-summary.md
python pipeline/build.py                              # classify into web/data/
```

`fetch.py` checks every layer's feature count against the server's own count and exits with an error if they differ.

To publish, commit the changed `web/` files and push to `main`. The GitHub Actions workflow in `.github/workflows/pages.yml` deploys `web/` to GitHub Pages, usually within a minute.

To preview locally first: `python -m http.server -d web 8000`, then open http://localhost:8000.

## Driver reports

What we collect: location, report type (camera / fine / zone missing or wrong / legal spot), date and time, and an optional photo of the sign.

What we never collect or publish: number plates, names, infringement notice numbers. Photos of fines must be cropped to the location details.

How reports become map data:
- Nothing goes live without moderation.
- A zone correction needs either a photo of the sign or two independent reports.
- Fine reports feed the heatmap only, never individual pins.

## Roadmap

- [x] **M1 Data:** `fetch.py` pulls lines, signs, clearways, loading zones and accessible parking for the v1 suburbs; `summarise.py` reports what's in them
- [x] **v0 preview:** `build.py` classifies in-service painted lines and loading zone signs into red, green and review; MapLibre page with a streets-only basemap, tap-for-details and locate-me, published on GitHub Pages
- [ ] **M2 Signs:** extend sign-only No Stopping zones from each sign's arrow; parse clearway hours
- [ ] **M3 Map:** clearways only red while active, search a venue and show the nearest green spot
- [ ] **M4 Cameras:** seed council-announced sites, mark each as announced, reported or confirmed
- [ ] **M5 Reports:** form, moderation flow, fine heatmap
- [ ] **M6 Ship to the group:** install prompt, "signs override this map" footer, feedback link
- [ ] **v2:** Spring Hill and Herston

## Known gaps

- No Stopping zones marked only by a sign (no paint) exist only as sign points. Where each zone starts and ends has to be inferred from the sign's arrow direction and the next sign along the kerb.
- Part-time restrictions (for example, a loading zone that becomes parking after 6pm) are only on the signs, and the days/times field is often blank.
- The camera network keeps growing, and there's no known live public list of every site.
- Council's own notes say its parking data is indicative and locations change. Check signs.

## Attribution

Contains data © Brisbane City Council (open data, CC BY 4.0; licence to be confirmed per dataset).
Not affiliated with Brisbane City Council, Uber or DiDi.
