# Decisions log

Every judgement call made on this project, so it can be audited or reversed later. Newest at the bottom.

Brendon delegated routine decisions on 26 Oct 2026 ("you approve and decide any decisions like this rather than asking me"). Anything marked **Assumption** is a guess about the real world that drivers or a site visit should confirm.

Format: what was decided, why, and how to change it.

---

### D001 · Project name and location (26 Oct 2026)
- **Decided:** repo `Babicean/brisbane-dropoff-map`; local copy in `Documents\brisbane-dropoff-map`.
- **Why:** the product is about where you can drop off, not only where you can't. Documents was empty and outside OneDrive, which doesn't play well with git.
- **Change:** rename on GitHub (Settings → General) and update the remote; move the folder freely.

### D002 · Commit author email (26 Oct 2026)
- **Decided:** commits use the GitHub no-reply address, not a personal email.
- **Why:** the repo is public; this keeps a personal email out of the history.
- **Change:** `git config user.email` in the repo.

### D003 · Scope (26 Oct 2026, Brendon)
- **Decided:** v1 = Brisbane City, Fortitude Valley, Newstead, Teneriffe, New Farm. v2 = Spring Hill, Herston (RBWH). South Bank excluded.
- **Why:** where the group reports fines. Newstead added because it was named originally and has a camera site. "Hospital area" confirmed as Herston.
- **Change:** `config/scope.json`.

### D004 · Data source and storage (26 Oct 2026)
- **Decided:** council ArcGIS layers are the source of truth. `fetch.py` is standard-library Python. Raw downloads (`data/raw/`) are not committed; processed map data (`web/data/`) is.
- **Why:** no install step on any machine; raw data is re-fetchable; committing the processed files means every data change shows up as a reviewable diff.
- **Change:** `.gitignore`, `config/layers.json`.

### D005 · Sources not used (26 Oct 2026)
- **Decided:** ignore the two loading zone point layers (stale Aug 2024 extracts of the sign data) and `BCC_Camera_Locations_view` (flood cameras, not parking).
- **Change:** `config/layers.json`.

### D006 · Hosting (26 Oct 2026, Brendon)
- **Decided:** repo made public; map hosted free on GitHub Pages, deployed by GitHub Actions on every push that touches `web/`.
- **Change:** repo Settings → Pages / General → visibility.

### D007 · Basemap and map library (26 Oct 2026)
- **Decided:** MapLibre GL JS 5.24.0 (pinned) with OpenFreeMap's Positron style.
- **Why:** free, no API key, no usage billing. Positron already has no business/POI layer, which matches "street names only".
- **Change:** `web/index.html`.

### D008 · What counts as red, green or review (26 Oct 2026)
- **Decided:** classification tables live in one place in code (now `pipeline/rules.py`). Red: no stopping, bus, taxi, mail, accessible, commercial-only loading, works zones, clearways when active. Green: loading zones that allow passengers, passenger loading zones, No Parking zones. Parking bays and meters aren't drawn. Anything unrecognised goes to review (amber), never silently to red or green.
- **Change:** `pipeline/rules.py`.

### D009 · Commercial vehicle loading zones are red (26 Oct 2026)
- **Assumption:** signs reading "Loading Zone Commercial Vehicle 20 Min. Max" don't allow passenger drop-offs. Council's fines table has a separate offence for stopping in a commercial vehicle loading zone without a permit.
- **Verify:** one photo of one of these signs from the group.
- **Change:** `LOADING_SIGNS` in `pipeline/rules.py`.

### D010 · Matching painted loading zones to signs (26 Oct 2026)
- **Decided:** a painted loading zone takes its type from the nearest loading zone sign within 25 m; with no sign in range it goes to review.
- **Change:** `SIGN_MATCH_METRES` in `pipeline/build.py`.

### D011 · Removed lines (26 Oct 2026)
- **Decided:** only `In Service` painted lines are drawn. `Disposal Complete` (removed from the road) are dropped; `Preliminary` goes to review.

### D012 · Preview warning on screen (26 Oct 2026)
- **Decided:** the bottom bar says "No red line doesn't mean you can stop" while sign-only zones are incomplete.
- **Change:** `.notice` in `web/index.html`.

### D013 · Backup before big changes (26 Oct 2026)
- **Decided:** the v0 preview is preserved as branch `backup/v0.1.0-preview` on GitHub (tag pushes are blocked from the build environment).
- **Restore:** reset `main` to that branch, or redeploy it from the Actions tab.

---

## Session 2 · 26 Oct 2026 (sign zones, timing, finder, cameras, reports, v2, auto-refresh)

### D014 · Road geometry from council, not OpenStreetMap
- **Decided:** kerb zones are drawn along council's road centreline layer (`BCC_SDRN_roads`, last edited Sept 2022).
- **Why:** OpenStreetMap's query servers weren't reachable from the build environment, and council's layer already uses the same street names as its sign data, so signs match their street exactly. Roads rarely move; 2022 is fine.
- **Also:** stopped fetching the two loading zone point layers and the accessible parking points: the sign layer covers all three.
- **Change:** `config/layers.json`.

### D015 · Sign arrow convention (checked on every build)
- **Decided:** a sign's arrow is read from the road, facing the kerb: for a sign on the left of the centreline's drawing direction, "Right" runs along that direction; on the right-hand side it runs the other way.
- **Evidence:** consecutive matching signs on the same kerb point at each other in 1,799 cases vs 182 pointing apart (91%). If the convention were backwards those numbers would swap. A check against painted yellow lines was much noisier (yellow lines often sit just outside a signed zone at corners), so it isn't used.
- **Safety:** `build.py` refuses to publish if this agreement drops below 80%.
- **Change:** `zones.validate_convention`, `MIN_CONVENTION_AGREEMENT` in `build.py`.

### D016 · How far a sign's rule runs
- **Decided:** from the sign to the next sign on the same kerb (any type except area-wide signs), or to the end of the block. Stops 6 m short of the intersection centre. A rule with no closing sign stops after 150 m and is labelled "end of zone estimated". Repeater signs merge into one stretch.
- **Change:** constants at the top of `pipeline/zones.py`.

### D017 · Painted lines win over sign zones
- **Decided:** where a sign zone overlaps a painted line of the same colour (within 4 m), only the paint is drawn. Green sign zones are also dropped where any paint (red or green) exists, so a sign-based guess never paints green over a yellow line.
- **Change:** `PAINT_COVER_M` in `zones.py`, `cover` in `build.py`.

### D018 · No Parking is green
- **Decided:** No Parking zones are green with the label "2 min drop-off, stay within 3 m of the car" (Qld road rules s168: stopping to drop off passengers is allowed for up to 2 minutes if you stay with the car).
- **Change:** `SIGN_RULES` in `pipeline/rules.py`.

### D019 · What isn't drawn
- **Decided:** ordinary parking (meters, 1P/2P, angle, motorcycle bays) isn't drawn. A quick drop-off there is normally fine, but it isn't what drivers ask about and drawing it would bury the map. These signs still end other zones. "Mail Zone or Australia Post Mail Box" signs go to review (a post box allows passenger drop-offs; a mail zone doesn't).
- **Change:** `pipeline/rules.py`.

### D020 · Hours: how timed rules are read
- **Decided:** council's hours text is parsed into weekly schedules (`pipeline/hours.py`, unit tested). "ALL OTHER TIMES" means outside the other panels on the same pole. "School days" is treated as every weekday (safe side). Public holidays are ignored. A timed rule whose hours can't be read is drawn as always in force and labelled "hours unclear, check the sign". A start time without am/pm takes the reading that makes sense with the end time (7–9:30am → 7am).
- **Coverage at build time:** 3,336 sign hour strings read, 8 unreadable; 151 timed clearways, 0 unreadable.
- **Change:** `pipeline/hours.py`.

### D021 · The map shows the rules for "now" by default
- **Decided:** the map evaluates timed rules for the current Brisbane time (no daylight saving, always UTC+10), refreshed every minute, with a picker to see another day/time. Rules not in force are drawn as thin grey dashes, not hidden, so drivers know a rule exists.
- **Change:** `applyTime()` in `web/index.html`.

### D022 · Drop-off finder
- **Decided:** search uses Photon (komoot), free and keyless, limited to the inner-city box; tapping the map works with no search at all. Shows the 3 nearest green spots in force at the selected time within 400 m, skipping duplicates within 25 m of each other. Walking distance is straight-line × 1.25, rounded.
- **Change:** `setDestination()` / `search()` in `web/index.html`.

### D023 · Cameras
- **Decided:** `config/cameras.json` lists every publicly named fixed parking camera street (council's 2025 releases plus Graham St and Park Rd from ABC News, Sept 2026). With no exact position, the whole street within that suburb is shaded blue and a white camera pin marks its middle. Reported/confirmed cameras with coordinates get a pin of their own (blue = confirmed).
- **Assumption:** council said 40+ sites exist but hasn't published the list; most are unknown to us.
- **Change:** `config/cameras.json`.

### D024 · Reports go through the group, not a server
- **Decided:** the Report button writes a message (type, nearest street, Google Maps link, note, time) and opens the phone's share sheet, or copies it. No backend, no accounts, nothing stored by the site. Brendon moderates: verified fixes go into `config/corrections.json` (hide features near a point, or add a note pin) and cameras into `config/cameras.json`.
- **Why:** the drivers already have a group chat; a backend would need hosting, spam control and a privacy policy.
- **Change:** `reportText()` in `web/index.html`; `apply_corrections()` in `build.py`.

### D025 · v2 suburbs are live
- **Decided:** the published map now covers Spring Hill and Herston as well (`"live": "v2"` in `config/scope.json`).

### D026 · Monthly automatic refresh
- **Decided:** `.github/workflows/refresh.yml` runs at 3:23 am Brisbane time on the 2nd of each month (and on demand): tests, fetch, build, and if the map layers changed, commit and deploy. `build.py` refuses to write if red < 1,500 or green < 150 features, or the arrow check fails, so a broken council download can't blank the map.
- **Note:** GitHub pauses scheduled workflows after 60 days with no repo activity; re-enable from the Actions tab if that happens.
- **Change:** `.github/workflows/refresh.yml`, `MIN_FEATURES` in `build.py`.

### D027 · Fines shown in the map
- **Decided:** amounts from council's fines page, penalty unit $172.70 from 1 July 2026: no stopping/yellow line/bus/taxi $345, clearway $518, accessible $690, mail zone/commercial loading zone/overstay $172, works zone $129. Update each July.
- **Change:** `FINES` in `pipeline/rules.py`, Info sheet in `web/index.html`.

### D028 · Night mode, home-screen app, offline
- **Decided:** the map follows the phone's dark mode (OpenFreeMap "dark" basemap). It can be added to the home screen (manifest + icons). A service worker serves the last-loaded map data when there's no signal, but always fetches fresh data when online.
- **Change:** `web/manifest.webmanifest`, `web/sw.js`, `web/icons/`.

### D029 · On-screen warning
- **Decided:** the bottom bar now reads "Signs always override this map. No stopping within 10 m of a corner, 20 m at lights." Sign-only zones are now drawn, so the old "no red line doesn't mean you can stop" warning was replaced with the most common undrawn rule (Qld road rules s170). "Preview" badge became "Beta".
- **Change:** `#notice` in `web/index.html`.

### D030 · Signs that can't be placed on a street
- **Decided:** signs more than 35 m from their own street (18 m from any street), mostly in car parks and hospital or school grounds, are shown as coloured dots rather than dropped.
- **Change:** `SNAP_*` constants in `pipeline/zones.py`.

---

## Independent review fixes · 27 Oct 2026

A separate review checked every rule against the Queensland Road Rules Regulation (reprint current 26 Jun 2026) and council's pages: no rule was wrong (loading zones s179(1)(d)(ii)/(2B), No Parking s168, taxi zones s182 taxis only, bus s183, mail s186, works s181, accessible s203; no extra rights for booked hire). It found ways the code could still show green where a driver can't stop. Fixed as follows.

### D031 · Green is never shown on a guess about hours
- **Decided:** a green rule whose hours are unreadable, "ALL OTHER TIMES" with no partner panel, school days, or days borrowed from another panel on the sign goes to review (amber) instead. Red rules keep using the best reading (over-covering is the safe side).
- **Change:** `parse_detail()` in `hours.py`; `sign_schedule()` in `zones.py`; `build.py`.

### D032 · Hours parser fixes
- **Decided:** day lists add up ("MON-FRI & SUN", "TUE THURS FRI"); "ALL DAY SUNDAY" is a full day; full day names are recognised; a lone letter ("… 7PM M") or other unknown word makes the text unreadable rather than guessing Monday; "M-SAT" is Monday–Saturday; "TOW AWAY"/"CLEARWAY"/"REPEATER" wording is ignored. Days given with no times ("SUN:-") are unreadable. Tests added for each.

### D033 · Green zones need a closing sign
- **Decided:** a sign-based green zone only runs all the way to the next pole if that pole has a sign of the same type pointing back. Otherwise it stops after 25 m and at least 16 m from the intersection centre (s170 corner rule), and the rest is amber "zone end not confirmed". Red zones still run to the next sign or the corner.
- **Change:** `GREEN_UNCLOSED_MAX_M`, `CORNER_CLEAR_M` in `zones.py`.

### D034 · Green never sits under red
- **Decided:** after everything is built, each green is checked against red lines and clearways on the same kerb (within 3.5 m, alongside rather than just touching at the ends):
  - a timed red covering 30%+ of a green takes its hours out of the green's;
  - a painted green with always-on red along more than half of it goes to review ("conflicting records"); smaller overlaps are left alone, because council's painted records overlap their neighbours by 3–4 m at the ends;
  - an inferred (sign-based) green is cut back wherever always-on red runs alongside.
- The drop-off finder also skips any spot within 4 m of red or a clearway in force at the selected time.
- **Change:** `resolve_green_conflicts()` in `build.py`; `setDestination()` in `web/index.html`.

### D035 · Other review fixes
- "ALL OTHER TIMES" uses only panels on the same pole pointing the same way (or both ways).
- A painted loading zone takes its type only from a loading zone sign on the same street and same side.
- Signs we can't place on a street that are green but have set hours show amber (their hours can't be shown on the map).
- Unrecognised sign types in restrictive categories (no stopping, loading, bus/taxi, no parking, accessible) go to review instead of being dropped. "Mail Zone or Australia Post Mail Box" signs are red (council files them under No Stopping; s186 has no passenger exception).
- Camera wording now says cameras catch illegal stops and misuse of loading zones, not any stop in a loading zone.

### D036 · Not changed (yet)
- **Public holidays** (s318: day-specific panels may not apply): noted in the time picker and Info sheet; no holiday calendar yet.
- **Motorcycle parking** may allow passenger drop-off (s202). Left undrawn until checked; it would only add green.
