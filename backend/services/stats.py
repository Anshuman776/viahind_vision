"""
Business analytics computed from persisted events, in the organization's timezone.

Definitions (also shown in the UI):
- entries / exits: line crossings that were not rejected by a reviewer.
- footfall: entries (people coming in). The same person entering twice counts twice.
- uncertain: crossings the system could not classify; excluded from all counts until reviewed.
- peak hour: the local hour of day with the most entries in the period.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.entities import Alert, Camera, DetectionEvent, Location, Visit
from services.occupancy import occupancy_changes
from services.site_settings import get_site_settings, local_day_bounds, site_zone

MAX_REPORT_DAYS = 400


def site_today(db: Session, organization_id: int) -> date:
    return datetime.now(site_zone(get_site_settings(db, organization_id))).date()


def _event_filters(organization_id: int, start: datetime, end: datetime, location_id: Optional[int], camera_id: Optional[str]):
    filters = [
        DetectionEvent.organization_id == organization_id,
        DetectionEvent.occurred_at >= start,
        DetectionEvent.occurred_at < end,
        DetectionEvent.review_status != "rejected",
    ]
    if location_id is not None:
        filters.append(DetectionEvent.location_id == location_id)
    if camera_id:
        filters.append(DetectionEvent.camera_id == camera_id)
    return filters


def day_summary(
    db: Session,
    organization_id: int,
    day: Optional[date] = None,
    location_id: Optional[int] = None,
    camera_id: Optional[str] = None,
) -> dict:
    row = get_site_settings(db, organization_id)
    day = day or site_today(db, organization_id)
    start, end = local_day_bounds(row, day)
    tz = site_zone(row)

    hourly = [{"hour": h, "entries": 0, "exits": 0} for h in range(24)]
    entries = exits = uncertain = 0
    q = select(DetectionEvent.occurred_at, DetectionEvent.event_type).where(*_event_filters(organization_id, start, end, location_id, camera_id))
    for occurred_at, kind in db.execute(q):
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
    visit_q = select(func.count(func.distinct(Visit.person_label))).where(
        Visit.organization_id == organization_id,
        Visit.entry_at >= start,
        Visit.entry_at < end,
        Visit.status != "voided",
        Visit.identified_by_operator.is_(False),
    )
    if location_id is not None:
        visit_q = visit_q.where(Visit.location_id == location_id)
    if camera_id:
        visit_q = visit_q.where(Visit.entry_camera_id == camera_id)
    unknown_visitors = db.scalar(visit_q) or 0

    peak = max(hourly, key=lambda b: b["entries"]) if entries else None
    return {
        "date": day.isoformat(),
        "timezone": row.timezone,
        "entries": entries,
        "exits": exits,
        "footfall": entries,
        "uncertain": uncertain,
        "unknown_visitors": unknown_visitors,
        "peak_hour": peak["hour"] if peak else None,
        "hourly": hourly,
    }


def _pct_change(current: float, previous: float) -> Optional[float]:
    if previous == 0:
        return None
    return round((current - previous) / previous * 100.0, 1)


def _totals(db: Session, organization_id: int, start: datetime, end: datetime, location_id, camera_id) -> Dict[str, int]:
    q = (
        select(DetectionEvent.event_type, func.count())
        .where(*_event_filters(organization_id, start, end, location_id, camera_id))
        .group_by(DetectionEvent.event_type)
    )
    counts = {k: n for k, n in db.execute(q)}
    return {"entries": counts.get("entry", 0), "exits": counts.get("exit", 0), "uncertain": counts.get("uncertain", 0)}


def period_report(
    db: Session,
    organization_id: int,
    date_from: date,
    date_to: date,
    location_id: Optional[int] = None,
    camera_id: Optional[str] = None,
) -> dict:
    """Footfall, entries/exits, peak hours, camera/location comparison and alerts for a date range,
    with the same-length previous period for comparison."""
    if date_to < date_from:
        raise ValueError("The end date is before the start date.")
    days = (date_to - date_from).days + 1
    if days > MAX_REPORT_DAYS:
        raise ValueError(f"Reports cover at most {MAX_REPORT_DAYS} days.")
    row = get_site_settings(db, organization_id)
    tz = site_zone(row)
    start = local_day_bounds(row, date_from)[0]
    end = local_day_bounds(row, date_to)[1]

    daily: Dict[str, dict] = {}
    for i in range(days):
        d = (date_from + timedelta(days=i)).isoformat()
        daily[d] = {"date": d, "entries": 0, "exits": 0, "uncertain": 0}
    hourly = [{"hour": h, "entries": 0, "exits": 0} for h in range(24)]
    weekday = [{"weekday": w, "entries": 0} for w in range(7)]
    by_camera: Dict[Optional[str], dict] = defaultdict(lambda: {"entries": 0, "exits": 0, "uncertain": 0})
    by_location: Dict[Optional[int], dict] = defaultdict(lambda: {"entries": 0, "exits": 0, "uncertain": 0})

    q = select(
        DetectionEvent.occurred_at, DetectionEvent.event_type, DetectionEvent.camera_id,
        DetectionEvent.location_id, DetectionEvent.source_camera_name,
    ).where(*_event_filters(organization_id, start, end, location_id, camera_id))
    remote_names: Dict[str, str] = {}
    for occurred_at, kind, cam_id, loc_id, remote_name in db.execute(q):
        local = occurred_at.astimezone(tz)
        key = {"entry": "entries", "exit": "exits"}.get(kind, "uncertain")
        bucket = daily.get(local.date().isoformat())
        if bucket is not None:
            bucket[key] += 1
        cam_key = cam_id or (f"remote:{remote_name}" if remote_name else None)
        if remote_name and not cam_id:
            remote_names[cam_key] = remote_name
        by_camera[cam_key][key] += 1
        by_location[loc_id][key] += 1
        if kind == "entry":
            hourly[local.hour]["entries"] += 1
            weekday[local.weekday()]["entries"] += 1
        elif kind == "exit":
            hourly[local.hour]["exits"] += 1

    totals = {
        "entries": sum(d["entries"] for d in daily.values()),
        "exits": sum(d["exits"] for d in daily.values()),
        "uncertain": sum(d["uncertain"] for d in daily.values()),
    }
    totals["footfall"] = totals["entries"]
    totals["avg_daily_footfall"] = round(totals["entries"] / days, 1)

    prev_start = local_day_bounds(row, date_from - timedelta(days=days))[0]
    previous = _totals(db, organization_id, prev_start, start, location_id, camera_id)
    comparison = {
        "previous_from": (date_from - timedelta(days=days)).isoformat(),
        "previous_to": (date_from - timedelta(days=1)).isoformat(),
        "previous": previous,
        "entries_change_pct": _pct_change(totals["entries"], previous["entries"]),
        "exits_change_pct": _pct_change(totals["exits"], previous["exits"]),
    }

    peak_hours = sorted((h for h in hourly if h["entries"]), key=lambda h: (-h["entries"], h["hour"]))[:3]

    cam_names = {c.id: (c.name, c.location_id) for c in db.scalars(select(Camera).where(Camera.organization_id == organization_id))}
    loc_names = {loc.id: loc.name for loc in db.scalars(select(Location).where(Location.organization_id == organization_id))}
    cameras = [
        {
            "camera_id": None if (k or "").startswith("remote:") else k,
            "camera_name": remote_names.get(k) or (cam_names.get(k, (k or "Deleted camera",))[0]),
            **v,
        }
        for k, v in by_camera.items()
    ]
    cameras.sort(key=lambda c: -c["entries"])
    locations = [{"location_id": k, "location_name": loc_names.get(k, "Unassigned"), **v} for k, v in by_location.items()]
    locations.sort(key=lambda c: -c["entries"])

    # Visit durations only where entry and exit were reliably linked (tracker or manual link).
    visit_q = select(Visit.entry_at, Visit.exit_at).where(
        Visit.organization_id == organization_id, Visit.status == "exited",
        Visit.entry_at >= start, Visit.entry_at < end, Visit.exit_at.is_not(None),
    )
    if location_id is not None:
        visit_q = visit_q.where(Visit.location_id == location_id)
    durations = [(b - a).total_seconds() for a, b in db.execute(visit_q) if a and b and b >= a]
    dwell = {
        "linked_visits": len(durations),
        "median_seconds": int(sorted(durations)[len(durations) // 2]) if durations else None,
    }

    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "days": days,
        "timezone": row.timezone,
        "totals": totals,
        "comparison": comparison,
        "daily": list(daily.values()),
        "hourly": hourly,
        "weekday": weekday,
        "peak_hours": peak_hours,
        "cameras": cameras,
        "locations": locations,
        "dwell": dwell,
        "alerts": alert_summary(db, organization_id, start, end, location_id, camera_id),
    }


def alert_summary(db: Session, organization_id: int, start: datetime, end: datetime,
                  location_id: Optional[int] = None, camera_id: Optional[str] = None) -> dict:
    filters = [Alert.organization_id == organization_id, Alert.first_seen_at >= start, Alert.first_seen_at < end]
    if location_id is not None:
        filters.append(Alert.location_id == location_id)
    if camera_id:
        filters.append(Alert.camera_id == camera_id)
    by_category: Dict[str, int] = {}
    by_severity: Dict[str, int] = {}
    by_status: Dict[str, int] = {}
    total = 0
    for category, severity, status, n in db.execute(
        select(Alert.category, Alert.severity, Alert.status, func.count()).where(*filters).group_by(Alert.category, Alert.severity, Alert.status)
    ):
        total += n
        by_category[category] = by_category.get(category, 0) + n
        by_severity[severity] = by_severity.get(severity, 0) + n
        by_status[status] = by_status.get(status, 0) + n
    return {"total": total, "by_category": by_category, "by_severity": by_severity, "by_status": by_status}


def occupancy_trend(db: Session, organization_id: int, location: Location, day: date) -> List[dict]:
    """Estimated occupancy at the end of each local hour of a day (and the hour's maximum),
    replayed from the last head count before the day, or zero. Hours in the future are null.
    Subject to the same drift as the live estimate."""
    row = get_site_settings(db, organization_id)
    tz = site_zone(row)
    start, end = local_day_bounds(row, day)
    last = _last_reconciliation_before(db, location.id, start)
    count = last.value if last else 0
    changes = occupancy_changes(db, organization_id, location.id, last.recorded_at if last else None, end)
    resets = _reconciliations_between(db, location.id, start, end)
    timeline = sorted([(at, "delta", d) for at, d in changes] + [(r.recorded_at, "reset", r.value) for r in resets], key=lambda c: c[0])

    now = datetime.now(tz)
    series = []
    idx = 0
    for h in range(24):
        hour_start = start + timedelta(hours=h)
        hour_end = hour_start + timedelta(hours=1)
        peak = count
        while idx < len(timeline) and timeline[idx][0] < hour_end:
            _at, kind, value = timeline[idx]
            count = value if kind == "reset" else max(0, count + value)
            peak = max(peak, count)
            idx += 1
        started = hour_start <= now
        series.append({"hour": h, "occupancy": count if started else None, "max": peak if started else None})
    return series


def _last_reconciliation_before(db: Session, location_id: int, before: datetime):
    from models.entities import OccupancySnapshot

    return db.scalar(
        select(OccupancySnapshot)
        .where(OccupancySnapshot.location_id == location_id, OccupancySnapshot.kind == "reconcile", OccupancySnapshot.recorded_at < before)
        .order_by(OccupancySnapshot.recorded_at.desc(), OccupancySnapshot.id.desc())
        .limit(1)
    )


def _reconciliations_between(db: Session, location_id: int, start: datetime, end: datetime):
    from models.entities import OccupancySnapshot

    return list(db.scalars(
        select(OccupancySnapshot)
        .where(OccupancySnapshot.location_id == location_id, OccupancySnapshot.kind == "reconcile",
               OccupancySnapshot.recorded_at >= start, OccupancySnapshot.recorded_at < end)
        .order_by(OccupancySnapshot.recorded_at)
    ))
