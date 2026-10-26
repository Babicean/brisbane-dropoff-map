"""Every red/green/review decision lives here. See docs/decisions.md (D008, D009, D014+).

Layer meanings on the map:
    red     don't stop (when active, for timed rules)
    green   a 2-minute passenger drop-off is legal
    review  shown amber: the data doesn't say clearly, check the signs
    None    not drawn (ordinary parking, meters, lane edges); still ends a zone
"""
from __future__ import annotations

# Penalties from Brisbane City Council's fines page, penalty unit $172.70 from 1 July 2026.
FINES = {
    "no_stopping": "$345 (2 penalty units)",
    "clearway": "$518 (3 penalty units)",
    "bus_zone": "$345 (2 penalty units)",
    "taxi_zone": "$345 (2 penalty units)",
    "mail_zone": "$172 (1 penalty unit)",
    "accessible": "$690 (4 penalty units)",
    "commercial_loading": "$172 (1 penalty unit)",
    "works_zone": "$129 (0.75 penalty units)",
    "loading_overstay": "$172 if you stay over 2 minutes",
    "no_parking_overstay": "$172 if you stay over 2 minutes or leave the car",
}


def norm(value) -> str:
    """Council text fields carry stray spaces ('Loading Zone ')."""
    return " ".join(str(value).split()) if value is not None else ""


# --- Painted lines (Parking_Line_locations.PARKINGRESTRICTIONTYPE) -----------

RED_LINES = {
    "No Stopping": ("No stopping (yellow line)", "no_stopping"),
    "Bus Bay": ("Bus zone", "bus_zone"),
    "Taxi Rank": ("Taxi rank: taxis only", "taxi_zone"),
    "Mail Zone": ("Mail zone", "mail_zone"),
    "Accessible Parking": ("Accessible bay: permit only", "accessible"),
}
LOADING_LINE = "Loading Zone"  # takes its type from the nearest loading zone sign
NOT_DRAWN_LINES = {"Parking - Parallel", "Parking - Angle", "Motorcycle Parking"}
NOT_DRAWN_SUBTYPES = {"Continuous Edge Line"}  # white lane edge, not a restriction


# --- Signs (Parking_Sign_locations.PARKINGRESTRICTIONTYPE) -------------------
# (layer, label, fine key). Matching is exact on the normalised type, then by prefix.

SIGN_RULES = {
    "No Stopping Any Time": ("red", "No stopping", "no_stopping"),
    "No Stopping Specified Times": ("red", "No stopping during signed hours", "no_stopping"),
    "No Stopping Police Vehicle Excepted": ("red", "No stopping (police excepted)", "no_stopping"),
    "Bus Zone": ("red", "Bus zone", "bus_zone"),
    "Bus Zone BCC": ("red", "Bus zone", "bus_zone"),
    "Bus Zone Other Bus Lane": ("red", "Bus zone", "bus_zone"),
    "Taxi Zone": ("red", "Taxi zone: taxis only", "taxi_zone"),
    "Accessible Parking": ("red", "Accessible parking: permit only", "accessible"),
    "Works Zone (Construction Vehicles)": ("red", "Works zone", "works_zone"),
    "Loading Zone Commercial Vehicle 20 Min. Max": ("red", "Commercial vehicle loading zone", "commercial_loading"),
    "Loading Zone - Passenger 2 Min. Max, Commercial Vehicles 20 Min. Max": ("green", "Loading zone: passengers 2 min", "loading_overstay"),
    "Loading Zone Passengers 2 Min. Max": ("green", "Passenger loading zone: 2 min", "loading_overstay"),
    "Loading Zone": ("green", "Loading zone: passengers 2 min", "loading_overstay"),
    "No Parking Any Time": ("green", "No Parking: 2 min drop-off, stay within 3 m of the car", "no_parking_overstay"),
    "No Parking Specified Times": ("green", "No Parking: 2 min drop-off, stay within 3 m of the car", "no_parking_overstay"),
    "Mail Zone or Australia Post Mail Box": ("red", "Mail zone", "mail_zone"),
}
SIGN_PREFIX_RULES = [
    ("No Stopping", ("red", "No stopping", "no_stopping")),
    ("Bus Zone", ("red", "Bus zone", "bus_zone")),
]
# Clearway signs are covered by council's separate clearway layer, so they
# aren't turned into zones here (they still end other zones).
CLEARWAY_SIGN_CATEGORY = "Clearway"
# Area-wide signs that say nothing about a stretch of kerb: ignore completely.
AREA_SIGN_CATEGORIES = {"Traffic Parking Control Areas"}
AREA_SIGN_TYPES = {"BRISBANE CENTRAL TRAFFIC AREA"}


# Sign categories that restrict stopping. A type in one of these we don't
# recognise goes to review rather than being silently left off the map.
RESTRICTIVE_CATEGORIES = {"No Stopping", "Loading Zones", "Bus Taxi & Special Vehicle Zones",
                          "No Parking", "Accessible Parking"}


def sign_rule(kind: str, category: str):
    """Return (layer, label, fine_key) for a sign, or None when it isn't drawn."""
    if category == CLEARWAY_SIGN_CATEGORY:
        return None
    if kind in SIGN_RULES:
        return SIGN_RULES[kind]
    for prefix, rule in SIGN_PREFIX_RULES:
        if kind.startswith(prefix):
            return rule
    if category in RESTRICTIVE_CATEGORIES:
        return ("review", f"{kind or 'Unrecognised sign'}: check the sign", None)
    return None


def ends_zones(kind: str, category: str) -> bool:
    """Does this sign mark a change of restriction along the kerb?"""
    return category not in AREA_SIGN_CATEGORIES and kind not in AREA_SIGN_TYPES and bool(kind)


# Loading zone signs used to type painted loading zone lines.
LOADING_SIGN_TYPES = {k for k in SIGN_RULES if k.startswith("Loading Zone")} | {"Works Zone (Construction Vehicles)"}
