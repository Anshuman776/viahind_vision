"""Daily and hourly aggregates, computed in the site's timezone from persisted events."""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.entities import DetectionEvent, Visit
from services.site_settings import get_site_settings, local_day_bounds, site_zone


def site_today(db: Session) -> date:
    return datetime.now(site_zone(get_site_settings(db))).date()


def day_summary(db: Session, day: Optional[date] = None) -> dict:
    row = get_site_settings(db)
    day = day or site_today(db)
    start, end = local_day_bounds(row, day)
    tz = site_zone(row)

    counted = (
        DetectionEvent.occurred_at >= start,
        DetectionEvent.occurred_at < end,
        DetectionEvent.review_status != "rejected",
    )
    hourly = [{"hour": h, "entries": 0, "exits": 0} for h in range(24)]
    entries = exits = uncertain = 0
    for occurred_at, kind in db.execute(select(DetectionEvent.occurred_at, DetectionEvent.event_type).where(*counted)):
        if kind == "uncertain":
            uncertain += 1
            continue
        bucket = hourly[occurred_at.astimezone(tz).hour]
        if kind == "entry":
            entries += 1
            bucket["entries"] += 1
        elif kind == "exit":
            exits += 1
            bucket["exits"] += 1

    # Distinct pseudonymous labels with an entry today that an operator has not identified.
    unknown_visitors = db.scalar(
        select(func.count(func.distinct(Visit.person_label))).where(
            Visit.entry_at >= start,
            Visit.entry_at < end,
            Visit.status != "voided",
            Visit.identified_by_operator.is_(False),
        )
    ) or 0

    return {
        "date": day.isoformat(),
        "timezone": row.timezone,
        "entries": entries,
        "exits": exits,
        "uncertain": uncertain,
        "unknown_visitors": unknown_visitors,
        "hourly": hourly,
    }
