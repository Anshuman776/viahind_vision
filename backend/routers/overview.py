from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from auth import require_operator, require_viewer
from config import settings
from db import get_db
from models.entities import OPEN_ALERT_STATUSES, Alert, Camera, DetectionEvent, Location, OccupancySnapshot, User
from models.schemas import AdjustRequest, ReconcileRequest
from runtime import runtime
from services import occupancy as occupancy_service
from services.events import serialize_event
from services.site_settings import get_site_settings, local_day_bounds, site_zone
from services.stats import day_summary, occupancy_trend, site_today
from services.tenancy import owned_camera, owned_location
from websocket import manager

router = APIRouter(tags=["overview"])


def _same_time_yesterday(db: Session, user: User, location_id: Optional[int], camera_id: Optional[str]) -> dict:
    """Entries/exits yesterday up to the current local time of day: a like-for-like comparison."""
    row = get_site_settings(db, user.organization_id)
    tz = site_zone(row)
    now_local = datetime.now(tz)
    start = local_day_bounds(row, now_local.date() - timedelta(days=1))[0]
    until = start + (now_local - now_local.replace(hour=0, minute=0, second=0, microsecond=0))
    q = select(DetectionEvent.event_type, func.count()).where(
        DetectionEvent.organization_id == user.organization_id,
        DetectionEvent.occurred_at >= start, DetectionEvent.occurred_at < until,
        DetectionEvent.review_status != "rejected",
    ).group_by(DetectionEvent.event_type)
    if location_id is not None:
        q = q.where(DetectionEvent.location_id == location_id)
    if camera_id:
        q = q.where(DetectionEvent.camera_id == camera_id)
    counts = dict(db.execute(q).all())
    return {"entries": counts.get("entry", 0), "exits": counts.get("exit", 0), "until_local_time": now_local.strftime("%H:%M")}


def _freshness(db: Session, user: User, location_id: Optional[int]) -> dict:
    q = select(func.max(DetectionEvent.occurred_at)).where(DetectionEvent.organization_id == user.organization_id)
    if location_id is not None:
        q = q.where(DetectionEvent.location_id == location_id)
    last_event = db.scalar(q)
    cam_q = select(Camera).where(Camera.organization_id == user.organization_id, Camera.enabled.is_(True))
    if location_id is not None:
        cam_q = cam_q.where(Camera.location_id == location_id)
    cams = list(db.scalars(cam_q))
    statuses = [runtime.cameras.status(c.id) if runtime.cameras else {"status": "stopped", "last_frame_at": None} for c in cams]
    frames = [s.get("last_frame_at") for s in statuses if s.get("last_frame_at")]
    sync = None
    if settings.IS_EDGE:
        from services.sync import outbox_status

        sync = outbox_status(db, user.organization_id)
    return {
        "last_event_at": last_event.isoformat() if last_event else None,
        "last_frame_at": max(frames) if frames else None,
        "cameras_total": len(cams),
        "cameras_live": sum(1 for s in statuses if s.get("status") == "live"),
        "cameras_problem": sum(1 for s in statuses if s.get("status") in ("error", "disconnected")),
        "pending_writes": runtime.recorder.pending_count() if runtime.recorder else 0,
        "deployment_mode": settings.DEPLOYMENT_MODE,
        "sync": sync,
    }


def _open_alerts(db: Session, user: User, location_id: Optional[int]) -> dict:
    q = select(Alert.severity, Alert.status, func.count()).where(
        Alert.organization_id == user.organization_id, Alert.status.in_(OPEN_ALERT_STATUSES)
    ).group_by(Alert.severity, Alert.status)
    if location_id is not None:
        q = q.where(Alert.location_id == location_id)
    by_severity, new = {}, 0
    total = 0
    for severity, status, n in db.execute(q):
        by_severity[severity] = by_severity.get(severity, 0) + n
        total += n
        if status == "new":
            new += n
    return {"open": total, "new": new, "by_severity": by_severity}


@router.get("/overview")
def overview(
    location_id: Optional[int] = None,
    camera_id: Optional[str] = Query(None, max_length=48),
    db: Session = Depends(get_db),
    user: User = Depends(require_viewer),
):
    """Everything the Overview page needs, from persisted records only."""
    owned_location(db, user, location_id)
    owned_camera(db, user, camera_id)
    data = {
        "occupancy": occupancy_service.compute_occupancy(db, user.organization_id, location_id),
        "today": day_summary(db, user.organization_id, location_id=location_id, camera_id=camera_id),
        "yesterday_same_time": _same_time_yesterday(db, user, location_id, camera_id),
        "alerts": _open_alerts(db, user, location_id),
        "freshness": _freshness(db, user, location_id),
        "recent_events": [],
    }
    if user.role != "viewer":
        q = select(DetectionEvent).where(DetectionEvent.organization_id == user.organization_id)
        if location_id is not None:
            q = q.where(DetectionEvent.location_id == location_id)
        if camera_id:
            q = q.where(DetectionEvent.camera_id == camera_id)
        recent = db.scalars(q.order_by(DetectionEvent.occurred_at.desc()).limit(10)).all()
        data["recent_events"] = [serialize_event(e, db) for e in recent]
    return data


@router.get("/stats/daily")
def daily(
    day: Optional[date] = Query(None),
    location_id: Optional[int] = None,
    camera_id: Optional[str] = Query(None, max_length=48),
    db: Session = Depends(get_db),
    user: User = Depends(require_viewer),
):
    owned_location(db, user, location_id)
    return day_summary(db, user.organization_id, day, location_id, camera_id)


@router.get("/occupancy")
def get_occupancy(location_id: Optional[int] = None, db: Session = Depends(get_db), user: User = Depends(require_viewer)):
    owned_location(db, user, location_id)
    return occupancy_service.compute_occupancy(db, user.organization_id, location_id)


@router.get("/occupancy/trend")
def get_occupancy_trend(location_id: int, day: Optional[date] = None, db: Session = Depends(get_db), user: User = Depends(require_viewer)):
    location = owned_location(db, user, location_id)
    day = day or site_today(db, user.organization_id)
    return {"date": day.isoformat(), "location_id": location.id, "hourly": occupancy_trend(db, user.organization_id, location, day)}


@router.get("/occupancy/history")
def occupancy_history(location_id: Optional[int] = None, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    q = select(OccupancySnapshot).where(OccupancySnapshot.organization_id == user.organization_id)
    if location_id is not None:
        q = q.where(OccupancySnapshot.location_id == location_id)
    rows = db.scalars(q.order_by(OccupancySnapshot.recorded_at.desc()).limit(50)).all()
    return [
        {"id": r.id, "location_id": r.location_id, "kind": r.kind, "value": r.value, "reason": r.reason,
         "recorded_at": r.recorded_at.isoformat(), "user_id": r.user_id}
        for r in rows
    ]


def _target_location(db: Session, user: User, location_id: Optional[int]) -> Location:
    if location_id is not None:
        return owned_location(db, user, location_id)
    locations = list(db.scalars(select(Location).where(Location.organization_id == user.organization_id, Location.is_active.is_(True)).limit(2)))
    if len(locations) != 1:
        raise HTTPException(status_code=422, detail="Choose the location to correct.")
    return locations[0]


def _after_change(db: Session, user: User, location_id: int) -> dict:
    db.commit()
    result = occupancy_service.compute_occupancy(db, user.organization_id, location_id)
    manager.broadcast_threadsafe({"type": "occupancy", "occupancy": result}, user.organization_id)
    return result


@router.post("/occupancy/reconcile")
def reconcile(body: ReconcileRequest, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    location = _target_location(db, user, body.location_id)
    try:
        occupancy_service.reconcile(db, user, location, body.count, body.reason)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _after_change(db, user, location.id)


@router.post("/occupancy/adjust")
def adjust(body: AdjustRequest, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    location = _target_location(db, user, body.location_id)
    try:
        occupancy_service.adjust(db, user, location, body.delta, body.reason)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _after_change(db, user, location.id)
