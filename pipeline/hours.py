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
WEEKDAYS = 0b0011111

# Single letters ('M', 'F') are only trusted in the pair 'M-F': a lone trailing 'M'
# in council text is usually a truncated word, not "Monday".
_DAY = (r"(?:MON(?:DAY)?|TUE(?:S(?:DAY)?)?|WED(?:S|NESDAY)?|THU(?:R(?:S(?:DAY)?)?)?|"
        r"FRI(?:DAY)?|SAT(?:URDAY)?|SUN(?:DAY)?)")
DAY_RE = re.compile(rf"\b(DAILY|WEEKDAYS|WEEKENDS?|M\s*-\s*(?:F|{_DAY})|{_DAY}(?:\s*-\s*(?:F\b|{_DAY}))?)\b")
TIME = r"(?:MIDNIGHT|12\s*NOON|NOON|\d{1,2}(?:[:.]\d{2})?\s*(?:AM|PM)?)"
RANGE_RE = re.compile(rf"({TIME})\s*(?:-|TO)\s*({TIME})")
SCHOOL_RE = re.compile(r"SCHOOL\s*DAYS?")


def _day_index(token: str) -> int:
    return DAYS.index(token[:3])


def _day_mask(spec: str) -> int:
    spec = re.sub(r"\s+", "", spec)
    if spec == "DAILY":
        return ALL_DAYS
    if spec in ("WEEKDAYS", "M-F"):
        return WEEKDAYS
    if spec.startswith("M-"):
        spec = "MON-" + spec[2:]
    if spec.endswith("-F"):
        spec = spec[:-2] + "-FRI"
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
    """Parse hours text. See parse_detail() for whether the reading was a guess."""
    return parse_detail(text)[0]


def parse_detail(text):
    """Return (result, approximate).

    approximate is True when the schedule involved a guess that could make a
    rule look in force when it isn't, or the reverse: school days read as every
    weekday, or a panel with no days borrowing them from another panel. Callers
    must not show a green (legal) stretch based on an approximate schedule.
    """
    if text is None:
        return None, False
    s = " ".join(str(text).upper().replace("–", "-").replace("—", "-").replace("&", " ").split())
    if not s or s in ("-",):
        return None, False
    if "OTHER TIME" in s:
        return OTHER_TIMES, False
    if "AT ALL TIMES" in s or s in ("ALL TIMES", "ANYTIME", "ANY TIME", "24 HOURS", "24HRS"):
        return ALWAYS, False
    # 'null:7 AM-9 AM ,MON-FRI:...' is a blank day field, like ':7am-9am ,MON-FRI:...'.
    s = re.sub(r"(^|,)\s*NULL\s*:", r"\1:", s)
    approximate = False
    if SCHOOL_RE.search(s):
        # School days are weekdays in term. Every weekday over-covers (school holidays).
        s = SCHOOL_RE.sub("MON-FRI", s)
        approximate = True
    if "NULL" in s:
        return None, False

    segments = [seg.strip() for seg in s.split(",") if seg.strip()]
    # Per segment: list of (ranges, mask or None) groups, plus any trailing day mask.
    parsed = []
    for seg in segments:
        tokens = [(m.start(), "day", _day_mask(m.group(1))) for m in DAY_RE.finditer(seg)]
        for m in RANGE_RE.finditer(seg):
            r = _range(m.group(1), m.group(2))
            if r is None or r[0] == r[1]:
                return None, False  # unreadable, or a zero-length range like '10 PM-10 PM'
            tokens.append((m.start(), "range", r))
        tokens.sort(key=lambda t: t[0])
        leftover = RANGE_RE.sub(" ", seg)
        leftover = DAY_RE.sub(" ", leftover).replace("ALL DAY", " ")
        leftover = re.sub(r"\b(TOW AWAY|CLEARWAY|REPEATER|ONLY)\b", " ", leftover)
        if re.search(r"[A-Z]", leftover):
            return None, False  # words we don't understand, e.g. a truncated '... M'
        has_range = any(t[1] == "range" for t in tokens)
        day_tokens = [t for t in tokens if t[1] == "day"]
        if not has_range:
            if "ALL DAY" in seg and day_tokens:
                mask = 0
                for t in day_tokens:
                    mask |= t[2]
                parsed.append(([(0, 1440)], mask, None))
                continue
            if day_tokens or re.search(r"\d", seg):
                return None, False  # days with no readable times ('SUN:-')
            continue
        # Days listed together ('MON-FRI SUN', 'TUE THURS FRI') add up. A new day
        # group starts after a range; trailing days ('7AM-9AM 4PM-7PM MON-FRI')
        # apply to the ranges before them that had no days of their own.
        groups, pending, current, unassigned = [], 0, None, []
        for _, kind, value in tokens:
            if kind == "day":
                pending |= value
            else:
                if pending:
                    current, pending = pending, 0
                if current is None:
                    unassigned.append(value)
                else:
                    groups.append(([value], current))
        if unassigned:
            if pending:  # '7AM-9AM 4PM-7PM MON-FRI'
                groups.append((unassigned, pending))
                unassigned = []
            elif groups:  # '7AM-9AM MON-FRI 4PM-6PM': the days after a range cover it
                groups.insert(0, (unassigned, groups[0][1]))
                unassigned = []
        parsed.append((None, None, (groups, unassigned)))

    if not parsed:
        return None, False

    def own_mask(entry):
        ranges, mask, detail = entry
        if detail is None:
            return mask
        groups, _ = detail
        return groups[0][1] if groups else None

    schedule = []
    for i, (ranges, mask, detail) in enumerate(parsed):
        if detail is None:
            for a, b in ranges:
                schedule.extend(_split(mask, a, b))
            continue
        groups, unassigned = detail
        for rs, m in groups:
            for a, b in rs:
                schedule.extend(_split(m, a, b))
        if unassigned:
            later = next((own_mask(e) for e in parsed[i + 1:] if own_mask(e)), None)
            earlier = next((own_mask(e) for e in reversed(parsed[:i]) if own_mask(e)), None)
            borrowed = later or earlier
            if borrowed:
                approximate = True
            for a, b in unassigned:
                schedule.extend(_split(borrowed or ALL_DAYS, a, b))
    result = normalise(schedule)
    return (result, approximate) if result else (None, False)


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


def subtract(schedule, *others):
    """Times in `schedule` not covered by any of `others`."""
    keep = _to_weekly(schedule)
    for other in others:
        cut = _to_weekly(other)
        out = []
        for a, b in keep:
            pieces = [(a, b)]
            for c, d in cut:
                nxt = []
                for x, y in pieces:
                    if d <= x or c >= y:
                        nxt.append((x, y))
                        continue
                    if c > x:
                        nxt.append((x, c))
                    if d < y:
                        nxt.append((d, y))
                pieces = nxt
            out.extend(pieces)
        keep = out
    return _from_weekly(sorted(keep))


def overlaps(a, b) -> bool:
    """Do two schedules share any time?"""
    spans_b = _to_weekly(b)
    return any(x < d and c < y for x, y in _to_weekly(a) for c, d in spans_b)


def decode(text: str):
    return [tuple(int(v) for v in part.split(",")) for part in text.split(";")] if text else []


def encode(schedule) -> str:
    """Compact form for the web map: 'mask,start,end;mask,start,end'."""
    return ";".join(f"{m},{s},{e}" for m, s, e in schedule)


def is_active(schedule, day: int, minute: int) -> bool:
    return any(mask & (1 << day) and start <= minute < end for mask, start, end in schedule)
