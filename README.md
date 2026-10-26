# Brisbane Drop-off Map

A map for rideshare drivers showing where you can and can't stop to drop off a passenger in inner Brisbane. Built from Brisbane City Council open data, then checked and corrected by drivers.

> **Status:** v1 in planning. Nothing is live yet.

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
| `Parking_Line_locations` | Line | `SUBURB`, `STREET`, `PARKINGRESTRICTIONTYPE`, `MARKINGCOLOUR`, `PAVEMENTLINELENGTH` | 19 Aug 2026 | Main red/green layer |
| `Parking_Clearways` | Line | `CATEGORY`, `OPERATIONAL_TIME` | 19 Oct 2026 | Time-aware red layer. No suburb field, so clip by area |
| `Parking_Sign_locations` | Point | `ASSETID`, `PARKINGRESTRICTIONTYPE` | Collected Apr 2020 – Aug 2021 | Sign-only zones (no paint). Extents must be inferred |
| Two Minute Passenger Loading zones | TBC | TBC | TBC | Green layer. *Layer URL to confirm* |
| Commercial Vehicle Loading zones | TBC | TBC | TBC | Subtract from green. *Layer URL to confirm* |

Technical notes:
- Layers support GeoJSON output and return at most **2,000 records per request**, so paginate with `resultOffset`.
- Some layers are stored in **EPSG:28356** (GDA94 / MGA zone 56). Request `outSR=4326` so the output is lat/long for the web map.
- The same datasets are mirrored on [data.brisbane.qld.gov.au](https://data.brisbane.qld.gov.au).

### How line types map to layers

| `PARKINGRESTRICTIONTYPE` | Layer | Note |
|---|---|---|
| No Stopping Line | Red | |
| Continuous Edge Line | Red **only if yellow** | Filter on `MARKINGCOLOUR`. White edge lines aren't no-stopping. Exact value to confirm |
| Bus Bay - Edge Line / No Edge Line | Red | |
| Taxi Rank | Red | |
| Mail Zone | Red | |
| Accessible Parking Bays (Angled / Parallel) | Red | Permit only |
| Loading Zone | Green | Unless it's a commercial vehicle loading zone. Cross-check that dataset |
| Special Purpose Zone, Unspecified Zone | Review | Check by hand before drawing |
| Angle / Parallel / Centre / Motorcycle parking bays | Not drawn in v1 | |

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

Each site has a "parking enforcement camera in use" sign. Exact camera positions get confirmed by driver reports.

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

### Planned repo layout

```
pipeline/        fetch and build scripts
data/raw/        untouched council downloads (gitignored)
web/             the map
web/data/        processed GeoJSON the map loads
docs/            rule references and research notes
```

## Driver reports

What we collect: location, report type (camera / fine / zone missing or wrong / legal spot), date and time, and an optional photo of the sign.

What we never collect or publish: number plates, names, infringement notice numbers. Photos of fines must be cropped to the location details.

How reports become map data:
- Nothing goes live without moderation.
- A zone correction needs either a photo of the sign or two independent reports.
- Fine reports feed the heatmap only, never individual pins.

## Roadmap

- [ ] **M1 Data:** `fetch.py` pulls lines and clearways for the v1 suburbs. Check record counts, suburb name spelling and `MARKINGCOLOUR` values
- [ ] **M2 Classify:** `build.py` outputs `red.geojson`, `green.geojson` and `clearways.geojson`
- [ ] **M3 Map:** MapLibre page with the street-names-only basemap, red/green layers, and clearways that follow the current time
- [ ] **M4 Cameras:** seed council-announced sites, mark each as announced, reported or confirmed
- [ ] **M5 Reports:** form, moderation flow, fine heatmap
- [ ] **M6 Ship to the group:** install prompt, "signs override this map" footer, feedback link
- [ ] **v2:** Spring Hill and Herston

## Known gaps

- No Stopping zones marked only by a sign (no paint) exist only as 2020–21 sign points. Where each zone starts and ends has to be inferred from arrow direction and the next sign.
- Part-time restrictions on signs (for example, a loading zone that becomes parking after 6pm) aren't in the lines data.
- The camera network keeps growing, and there's no known live public list of every site.
- Council's own notes say its parking data is indicative and locations change. Check signs.

## Attribution

Contains data © Brisbane City Council (open data, CC BY 4.0; licence to be confirmed per dataset).
Not affiliated with Brisbane City Council, Uber or DiDi.
