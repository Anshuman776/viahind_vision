"""Business hours per location: {"mon": [["09:00", "21:00"]], ...} in the organization timezone.

A day that is missing or has an empty list is closed. A range whose end is earlier than its start
runs past midnight (e.g. ["18:00", "02:00"] for a late restaurant).
"""

import json
import re
from datetime import datetime, time, timedelta
from typing import Dict, List, Optional

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

Hours = Dict[str, List[List[str]]]


def validate_hours(value: Optional[dict]) -> Optional[Hours]:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Business hours must be an object keyed by day (mon..sun).")
    out: Hours = {}
    for day, ranges in value.items():
        if day not in DAYS:
            raise ValueError(f"Unknown day '{day}'. Use mon, tue, wed, thu, fri, sat, sun.")
        if not isinstance(ranges, list) or len(ranges) > 4:
            raise ValueError("Each day takes up to 4 [open, close] ranges.")
        cleaned = []
        for r in ranges:
            if not (isinstance(r, (list, tuple)) and len(r) == 2 and all(isinstance(x, str) and HHMM.match(x) for x in r)):
                raise ValueError("Ranges are [\"HH:MM\", \"HH:MM\"] in 24-hour time.")
            if r[0] == r[1]:
                raise ValueError("A range cannot open and close at the same time.")
            cleaned.append([r[0], r[1]])
        out[day] = cleaned
    return out


def parse_hours(raw: Optional[str]) -> Optional[Hours]:
    if not raw:
        return None
    try:
        return validate_hours(json.loads(raw))
    except (ValueError, json.JSONDecodeError):
        return None


def _t(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def is_open(local: datetime, hours: Hours, grace_minutes: int = 0) -> bool:
    """Whether a local datetime falls inside business hours (widened by grace on both ends)."""
    grace = timedelta(minutes=grace_minutes)
    for offset in (0, -1):  # today's ranges, and yesterday's ranges that run past midnight
        day = (local + timedelta(days=offset)).date()
        for start_s, end_s in hours.get(DAYS[day.weekday()], []):
            start = datetime.combine(day, _t(start_s), tzinfo=local.tzinfo)
            end = datetime.combine(day, _t(end_s), tzinfo=local.tzinfo)
            if end <= start:
                end += timedelta(days=1)
            if start - grace <= local < end + grace:
                return True
    return False
