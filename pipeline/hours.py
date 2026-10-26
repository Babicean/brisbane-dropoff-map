"""Parse council parking hours text into weekly schedules.

Council writes hours in many formats, for example:
    signs:     'MON-FRI:7am-9am'   ':7am-9am ,MON-FRI:4pm-6pm'   'DAILY:MIDNIGHT-5:30 AM'
    clearways: '7AM-9AM  4PM-7PM MON-FRI'   '4PM-7PM M-F'   'AT ALL TIMES'

A schedule is a list of (day_mask, start_minute, end_minute) intervals in
Brisbane local time, Monday = bit 0 ... Sunday = bit 6, 0 <= start < end <= 1440.

parse() returns:
    ALWAYS          the restriction applies at all times
    OTHER_TIMES     "ALL OTHER TIMES": the complement of the other panels on the same pole
    a schedule      a non-empty list of intervals
    None            couldn't be understood: callers must treat it as "check the sign"
"""
from __future__ import annotations

import re

ALWAYS = "always"
OTHER_TIMES = "other_times"

DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
ALL_DAYS = 0b1111111
DAY_ALIASES = {"M": "MON", "F": "FRI", "TUES": "TUE", "THUR": "THU", "THURS": "THU", "WEDS": "WED"}

_DAY = r"(?:MON|TUES?|WEDS?|THU(?:RS?)?|FRI|SAT|SUN|M|F)"
DAY_RE = re.compile(rf"\b(DAILY|WEEKDAYS|WEEKENDS?|{_DAY}(?:\s*-\s*{_DAY})?)\b")
TIME = r"(?:MIDNIGHT|12\s*NOON|NOON|\d{1,2}(?:[:.]\d{2})?\s*(?:AM|PM)?)"
RANGE_RE = re.compile(rf"({TIME})\s*(?:-|TO)\s*({TIME})")


def _day_index(token: str) -> int:
    token = DAY_ALIASES.get(token, token)
    return DAYS.index(token[:3])


def _day_mask(spec: str) -> int:
    spec = re.sub(r"\s+", "", spec)
    if spec == "DAILY":
        return ALL_DAYS
    if spec == "WEEKDAYS":
        return 0b0011111
    if spec.startswith("WEEKEND"):
        return 0b1100000
    if "-" in spec:
        a, b = (_day_index(t) for t in spec.split("-"))
        mask, i = 0, a
        while True:
            mask |= 1 << i
            if i == b:
                break
            i = (i + 1) % 7
        return mask
    return 1 << _day_index(spec)


def _time(token: str):
    """Return (minutes, has_meridiem) or None. Meridiem-less hours are resolved later."""
    t = re.sub(r"\s+", "", token)
    if t == "MIDNIGHT":
        return ("midnight", True)
    if t in ("NOON", "12NOON"):
        return (720, True)
    m = re.fullmatch(r"(\d{1,2})(?:[:.](\d{2}))?(AM|PM)?", t)
    if not m:
        return None
    h, mins, mer = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if h > 23 or mins > 59:
        return None
    if mer:
        if h > 12 or h == 0:
            return None
        h = h % 12 + (12 if mer == "PM" else 0)
        return (h * 60 + mins, True)
    return (h * 60 + mins, False)


def _range(a_tok: str, b_tok: str):
    a, b = _time(a_tok), _time(b_tok)
    if a is None or b is None:
        return None
    (a_min, a_mer), (b_min, b_mer) = a, b
    if a_min == "midnight":
        a_min = 0
    if b_min == "midnight":
        b_min = 1440
    if not b_mer:
        return None  # e.g. '7-9' with no am/pm anywhere: too ambiguous
    if not a_mer:
        # '7-9:30am', '3:30-7pm', '11-2pm': pick the reading that gives a sensible span.
        am, pm = a_min % 720, a_min % 720 + 720
        candidates = [c for c in (am, pm) if c < b_min]
        a_min = max(candidates) if candidates else am
    return a_min, b_min


def parse(text):
    if text is None:
        return None
    s = " ".join(str(text).upper().replace("–", "-").replace("—", "-").split())
    if not s or s in ("-",):
        return None
    if "OTHER TIME" in s:
        return OTHER_TIMES
    if "AT ALL TIMES" in s or s in ("ALL TIMES", "ANYTIME", "ANY TIME", "24 HOURS", "24HRS"):
        return ALWAYS
    # 'null:7 AM-9 AM ,MON-FRI:...' is a blank day field, like ':7am-9am ,MON-FRI:...'.
    s = re.sub(r"(^|,)\s*NULL\s*:", r"\1:", s)
    # School days are weekdays in term; treating them as every weekday errs on the safe side.
    s = s.replace("SCHOOL DAYS", "MON-FRI")
    if "NULL" in s:
        return None

    schedule = []
    segments = [seg.strip() for seg in s.split(",") if seg.strip()]
    seg_days = []
    seg_ranges = []
    for seg in segments:
        # Word boundaries stop 'M' matching inside 'AM' or 'MIDNIGHT'.
        days = [(m.start(), _day_mask(m.group(1))) for m in DAY_RE.finditer(seg)]
        ranges = []
        for m in RANGE_RE.finditer(seg):
            r = _range(m.group(1), m.group(2))
            if r is None or r[0] == r[1]:
                return None  # unreadable, or a zero-length range like '10 PM-10 PM'

            ranges.append((m.start(), r))
        seg_days.append(days)
        seg_ranges.append(ranges)

    if not any(seg_ranges):
        return None

    for i, ranges in enumerate(seg_ranges):
        for pos, (start, end) in ranges:
            days = seg_days[i]
            mask = None
            if days:
                before = [m for p, m in days if p < pos]
                mask = before[-1] if before else days[0][1]
            else:
                later = next((d for d in seg_days[i + 1:] if d), None)
                earlier = next((d for d in reversed(seg_days[:i]) if d), None)
                mask = (later or earlier or [(0, ALL_DAYS)])[0][1]
            schedule.extend(_split(mask, start, end))
    return normalise(schedule) or None


def _split(mask: int, start: int, end: int):
    """Intervals that cross midnight become two: tonight's part and tomorrow morning's."""
    if end > start:
        return [(mask, start, end)]
    if end == start:
        return [(mask, 0, 1440)]
    tomorrow = ((mask << 1) | (mask >> 6)) & ALL_DAYS
    return [(mask, start, 1440), (tomorrow, 0, end)]


def _to_weekly(schedule):
    """Expand to a sorted list of (start, end) minute ranges across the week (0..10080)."""
    spans = []
    for mask, start, end in schedule:
        for d in range(7):
            if mask & (1 << d):
                spans.append((d * 1440 + start, d * 1440 + end))
    spans.sort()
    merged = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def _from_weekly(spans):
    out = []
    for a, b in spans:
        while a < b:
            d, start = divmod(a, 1440)
            end = min(b - d * 1440, 1440)
            out.append((1 << d, start, end))
            a = d * 1440 + end
    # Merge identical day-independent intervals into one mask.
    by_time = {}
    for mask, start, end in out:
        by_time[(start, end)] = by_time.get((start, end), 0) | mask
    return sorted(((m, s, e) for (s, e), m in by_time.items()), key=lambda t: (t[1], t[2], t[0]))


def normalise(schedule):
    return _from_weekly(_to_weekly(schedule))


def complement(schedules):
    """The times not covered by any of the given schedules."""
    covered = _to_weekly([iv for sch in schedules for iv in sch])
    gaps, cursor = [], 0
    for a, b in covered:
        if a > cursor:
            gaps.append((cursor, a))
        cursor = max(cursor, b)
    if cursor < 7 * 1440:
        gaps.append((cursor, 7 * 1440))
    return _from_weekly(gaps)


def encode(schedule) -> str:
    """Compact form for the web map: 'mask,start,end;mask,start,end'."""
    return ";".join(f"{m},{s},{e}" for m, s, e in schedule)


def is_active(schedule, day: int, minute: int) -> bool:
    return any(mask & (1 << day) and start <= minute < end for mask, start, end in schedule)
