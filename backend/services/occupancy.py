"""
Occupancy ("People Currently Inside") derived from persisted records.

    occupancy = last reconciliation value (0 if never reconciled)
              + confirmed entries - confirmed exits - / + manual adjustments since then

applied in time order and never allowed to go below zero. Uncertain and rejected events do
not count. The figure is flagged as *estimated* when, since the last reconciliation:
- an exit arrived while the count was already 0 (an entry was missed),
- a camera disconnected, errored or the service restarted (events may have been missed),
- uncertain events are still waiting for review.
Operators clear the estimate by reconciling with a head count.
"""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from db import utcnow
from models.entities import Camera, CameraIncident, DetectionEvent, OccupancySnapshot, User
from services.audit import record_audit
from services.site_settings import get_site_settings, site_zone

MAX_OCCUPANCY = 10000


def _last_reconciliation(db: Session) -> Optional[OccupancySnapshot]:
    return db.scalar(
        select(OccupancySnapshot)
        .where(OccupancySnapshot.kind == "reconcile")
        .order_by(OccupancySnapshot.recorded_at.desc(), OccupancySnapshot.id.desc())
        .limit(1)
    )


def compute_occupancy(db: Session) -> dict:
    last = _last_reconciliation(db)
    since: Optional[datetime] = last.recorded_at if last else None
    count = last.value if last else 0

    event_q = select(DetectionEvent.occurred_at, DetectionEvent.event_type).where(
        DetectionEvent.event_type.in_(("entry", "exit")),
        DetectionEvent.review_status != "rejected",
    )
    adjust_q = select(OccupancySnapshot.recorded_at, OccupancySnapshot.value).where(OccupancySnapshot.kind == "adjust")
    if since is not None:
        event_q = event_q.where(DetectionEvent.occurred_at > since)
        adjust_q = adjust_q.where(OccupancySnapshot.recorded_at > since)

    changes = [(at, 1 if kind == "entry" else -1) for at, kind in db.execute(event_q)]
    changes += [(at, value) for at, value in db.execute(adjust_q)]
    changes.sort(key=lambda c: c[0])

    underflows = 0
    for _, delta in changes:
        count += delta
        if count < 0:
            underflows += 1
            count = 0

    reasons: List[str] = []
    if underflows:
        reasons.append(f"{underflows} exit(s) were recorded while the count was already zero; an entry was probably missed.")

    incident_q = select(CameraIncident, Camera.name).outerjoin(Camera, Camera.id == CameraIncident.camera_id)
    if since is not None:
        # Interruptions still ongoing, or that lasted past the last head count.
        incident_q = incident_q.where(or_(CameraIncident.ended_at.is_(None), CameraIncident.ended_at > since))
    incidents = db.execute(incident_q.order_by(CameraIncident.started_at.desc()).limit(20)).all()
    if incidents:
        tz = site_zone(get_site_settings(db))
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
        DetectionEvent.event_type == "uncertain", DetectionEvent.review_status == "needs_review"
    )
    if since is not None:
        uncertain_q = uncertain_q.where(DetectionEvent.occurred_at > since)
    pending_uncertain = db.scalar(uncertain_q) or 0
    if pending_uncertain:
        reasons.append(f"{pending_uncertain} uncertain event(s) are waiting for review.")

    return {
        "count": count,
        "estimated": bool(reasons),
        "reasons": reasons,
        "last_reconciled_at": last.recorded_at.isoformat() if last else None,
        "last_reconciled_value": last.value if last else None,
    }


def reconcile(db: Session, user: User, count: int, reason: str) -> OccupancySnapshot:
    if not 0 <= count <= MAX_OCCUPANCY:
        raise ValueError("Occupancy must be between 0 and 10000.")
    before = compute_occupancy(db)["count"]
    now = utcnow()
    snap = OccupancySnapshot(kind="reconcile", value=count, reason=reason.strip(), user_id=user.id, recorded_at=now)
    db.add(snap)
    db.flush()
    record_audit(db, user, "occupancy.reconcile", "occupancy", snap.id, {"before": before, "after": count, "reason": snap.reason})
    return snap


def adjust(db: Session, user: User, delta: int, reason: str) -> OccupancySnapshot:
    if delta == 0 or abs(delta) > 100:
        raise ValueError("Adjustment must be a non-zero value between -100 and 100.")
    before = compute_occupancy(db)["count"]
    snap = OccupancySnapshot(kind="adjust", value=delta, reason=reason.strip(), user_id=user.id, recorded_at=utcnow())
    db.add(snap)
    db.flush()
    record_audit(db, user, "occupancy.adjust", "occupancy", snap.id, {"before": before, "delta": delta, "reason": snap.reason})
    return snap
