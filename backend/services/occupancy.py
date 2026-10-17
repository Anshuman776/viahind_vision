"""
Occupancy ("people currently inside") derived from persisted records, per location.

    occupancy = last reconciliation value (0 if never reconciled)
              + entries - exits +/- manual adjustments since then

applied in time order and never allowed to go below zero. Uncertain and rejected events do
not count. The figure is flagged as *estimated* when, since the last reconciliation:
- an exit arrived while the count was already 0 (an entry was missed),
- a camera disconnected, errored or the service restarted (events may have been missed),
- uncertain events are still waiting for review.
Operators clear the estimate by reconciling with a head count.

Known limitations: missed detections, occlusion and multiple uncounted entrances make the figure
drift; it is an estimate to be reconciled, not a head count.
"""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from db import utcnow
from models.entities import Camera, CameraIncident, DetectionEvent, Location, OccupancySnapshot, User
from services.audit import record_audit
from services.site_settings import get_site_settings, site_zone

MAX_OCCUPANCY = 10000


def _last_reconciliation(db: Session, location_id: int) -> Optional[OccupancySnapshot]:
    return db.scalar(
        select(OccupancySnapshot)
        .where(OccupancySnapshot.location_id == location_id, OccupancySnapshot.kind == "reconcile")
        .order_by(OccupancySnapshot.recorded_at.desc(), OccupancySnapshot.id.desc())
        .limit(1)
    )


def occupancy_changes(db: Session, organization_id: int, location_id: int, since: Optional[datetime], until: Optional[datetime] = None):
    """Time-ordered (timestamp, delta) occupancy changes for one location."""
    event_q = select(DetectionEvent.occurred_at, DetectionEvent.event_type).where(
        DetectionEvent.organization_id == organization_id,
        DetectionEvent.location_id == location_id,
        DetectionEvent.event_type.in_(("entry", "exit")),
        DetectionEvent.review_status != "rejected",
    )
    adjust_q = select(OccupancySnapshot.recorded_at, OccupancySnapshot.value).where(
        OccupancySnapshot.location_id == location_id, OccupancySnapshot.kind == "adjust"
    )
    if since is not None:
        event_q = event_q.where(DetectionEvent.occurred_at > since)
        adjust_q = adjust_q.where(OccupancySnapshot.recorded_at > since)
    if until is not None:
        event_q = event_q.where(DetectionEvent.occurred_at <= until)
        adjust_q = adjust_q.where(OccupancySnapshot.recorded_at <= until)
    changes = [(at, 1 if kind == "entry" else -1) for at, kind in db.execute(event_q)]
    changes += [(at, value) for at, value in db.execute(adjust_q)]
    changes.sort(key=lambda c: c[0])
    return changes


def compute_location_occupancy(db: Session, organization_id: int, location: Location) -> dict:
    last = _last_reconciliation(db, location.id)
    since: Optional[datetime] = last.recorded_at if last else None
    count = last.value if last else 0

    underflows = 0
    for _, delta in occupancy_changes(db, organization_id, location.id, since):
        count += delta
        if count < 0:
            underflows += 1
            count = 0

    reasons: List[str] = []
    if underflows:
        reasons.append(f"{underflows} exit(s) were recorded while the count was already zero; an entry was probably missed.")

    incident_q = (
        select(CameraIncident, Camera.name)
        .join(Camera, Camera.id == CameraIncident.camera_id)
        .where(CameraIncident.organization_id == organization_id, Camera.location_id == location.id)
    )
    if since is not None:
        # Interruptions still ongoing, or that lasted past the last head count.
        incident_q = incident_q.where(or_(CameraIncident.ended_at.is_(None), CameraIncident.ended_at > since))
    incidents = db.execute(incident_q.order_by(CameraIncident.started_at.desc()).limit(20)).all()
    if incidents:
        tz = site_zone(get_site_settings(db, organization_id))
        fmt = lambda dt: dt.astimezone(tz).strftime("%d %b %I:%M %p")
        ongoing = [(i, n) for i, n in incidents if i.ended_at is None]
        ended = [(i, n) for i, n in incidents if i.ended_at is not None]
        for incident, name in ongoing:
            reasons.append(f"{name or 'A camera'} is not delivering video (camera interruption since {fmt(incident.started_at)}); entries and exits are not being recorded.")
        if ended:
            spans = ", ".join(f"{n or 'a camera'} {fmt(i.started_at)} – {fmt(i.ended_at)}" for i, n in ended[:3])
            more = f" and {len(ended) - 3} more" if len(ended) > 3 else ""
            reasons.append(f"Events may have been missed during {len(ended)} earlier camera interruption(s): {spans}{more}. Reconcile with a head count to confirm the figure.")

    uncertain_q = select(func.count()).select_from(DetectionEvent).where(
        DetectionEvent.organization_id == organization_id,
        DetectionEvent.location_id == location.id,
        DetectionEvent.event_type == "uncertain",
        DetectionEvent.review_status == "needs_review",
    )
    if since is not None:
        uncertain_q = uncertain_q.where(DetectionEvent.occurred_at > since)
    pending_uncertain = db.scalar(uncertain_q) or 0
    if pending_uncertain:
        reasons.append(f"{pending_uncertain} uncertain event(s) are waiting for review.")

    return {
        "location_id": location.id,
        "location_name": location.name,
        "capacity": location.capacity,
        "count": count,
        "estimated": bool(reasons),
        "reasons": reasons,
        "last_reconciled_at": last.recorded_at.isoformat() if last else None,
        "last_reconciled_value": last.value if last else None,
    }


def compute_occupancy(db: Session, organization_id: int, location_id: Optional[int] = None) -> dict:
    """Occupancy for one location, or the organization total across its active locations."""
    q = select(Location).where(Location.organization_id == organization_id)
    if location_id is not None:
        q = q.where(Location.id == location_id)
    else:
        q = q.where(Location.is_active.is_(True))
    locations = list(db.scalars(q.order_by(Location.name)))
    parts = [compute_location_occupancy(db, organization_id, loc) for loc in locations]
    if location_id is not None and parts:
        result = dict(parts[0])
        result["locations"] = parts
        return result
    multi = len(parts) > 1
    reasons = [f"{p['location_name']}: {r}" if multi else r for p in parts for r in p["reasons"]]
    reconciled = [p["last_reconciled_at"] for p in parts if p["last_reconciled_at"]]
    return {
        "location_id": None,
        "location_name": None,
        "capacity": None,
        "count": sum(p["count"] for p in parts),
        "estimated": any(p["estimated"] for p in parts),
        "reasons": reasons,
        # The oldest head count among the locations (null until every location has one).
        "last_reconciled_at": min(reconciled) if parts and len(reconciled) == len(parts) else None,
        "last_reconciled_value": parts[0]["last_reconciled_value"] if len(parts) == 1 else None,
        "locations": parts,
    }


def reconcile(db: Session, user: User, location: Location, count: int, reason: str) -> OccupancySnapshot:
    if not 0 <= count <= MAX_OCCUPANCY:
        raise ValueError("Occupancy must be between 0 and 10000.")
    before = compute_location_occupancy(db, user.organization_id, location)["count"]
    snap = OccupancySnapshot(
        organization_id=user.organization_id, location_id=location.id, kind="reconcile",
        value=count, reason=reason.strip(), user_id=user.id, recorded_at=utcnow(),
    )
    db.add(snap)
    db.flush()
    record_audit(db, user, "occupancy.reconcile", "occupancy", snap.id,
                 {"location_id": location.id, "before": before, "after": count, "reason": snap.reason})
    return snap


def adjust(db: Session, user: User, location: Location, delta: int, reason: str) -> OccupancySnapshot:
    if delta == 0 or abs(delta) > 100:
        raise ValueError("Adjustment must be a non-zero value between -100 and 100.")
    before = compute_location_occupancy(db, user.organization_id, location)["count"]
    snap = OccupancySnapshot(
        organization_id=user.organization_id, location_id=location.id, kind="adjust",
        value=delta, reason=reason.strip(), user_id=user.id, recorded_at=utcnow(),
    )
    db.add(snap)
    db.flush()
    record_audit(db, user, "occupancy.adjust", "occupancy", snap.id,
                 {"location_id": location.id, "before": before, "delta": delta, "reason": snap.reason})
    return snap
