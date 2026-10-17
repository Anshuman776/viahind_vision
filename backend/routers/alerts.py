"""Alert review: list, detail with evidence, acknowledge / resolve / dismiss / reopen."""

from datetime import date
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from auth import require_operator
from db import get_db
from models.entities import OPEN_ALERT_STATUSES, Alert, NotificationDelivery, User
from models.schemas import AlertAction
from services.alert_rules import CATEGORIES
from services.alerts import TransitionError, serialize_alert, transition
from services.audit import audit_trail
from services.notifications import serialize_delivery
from services.site_settings import get_site_settings, local_day_bounds
from services.snapshots import snapshot_file
from services.tenancy import get_owned
from websocket import manager

router = APIRouter(prefix="/alerts", tags=["alerts"])

Status = Optional[Literal["new", "acknowledged", "resolved", "dismissed", "open"]]
Severity = Optional[Literal["info", "low", "medium", "high", "critical"]]


@router.get("")
def list_alerts(
    status: Status = None,
    severity: Severity = None,
    category: Optional[str] = Query(None, max_length=32),
    location_id: Optional[int] = None,
    camera_id: Optional[str] = Query(None, max_length=48),
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
):
    q = select(Alert).where(Alert.organization_id == user.organization_id)
    if status == "open":
        q = q.where(Alert.status.in_(OPEN_ALERT_STATUSES))
    elif status:
        q = q.where(Alert.status == status)
    if severity:
        q = q.where(Alert.severity == severity)
    if category:
        q = q.where(Alert.category == category)
    if location_id is not None:
        q = q.where(Alert.location_id == location_id)
    if camera_id:
        q = q.where(Alert.camera_id == camera_id)
    row = get_site_settings(db, user.organization_id)
    if date_from:
        q = q.where(Alert.last_seen_at >= local_day_bounds(row, date_from)[0])
    if date_to:
        q = q.where(Alert.first_seen_at < local_day_bounds(row, date_to)[1])
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(q.order_by(Alert.last_seen_at.desc(), Alert.id).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [serialize_alert(a, db) for a in rows], "total": total, "page": page, "page_size": page_size,
            "categories": CATEGORIES}


@router.get("/summary")
def alert_counts(db: Session = Depends(get_db), user: User = Depends(require_operator)):
    rows = db.execute(
        select(Alert.status, func.count()).where(Alert.organization_id == user.organization_id, Alert.status.in_(OPEN_ALERT_STATUSES))
        .group_by(Alert.status)
    ).all()
    counts = dict(rows)
    return {"new": counts.get("new", 0), "acknowledged": counts.get("acknowledged", 0)}


def _get(db: Session, alert_id: str, user: User) -> Alert:
    return get_owned(db, Alert, alert_id, user, "Alert not found.")


@router.get("/{alert_id}")
def get_alert(alert_id: str, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    alert = _get(db, alert_id, user)
    data = serialize_alert(alert, db)
    data["audit"] = audit_trail(db, user.organization_id, "alert", alert.id)
    data["deliveries"] = [serialize_delivery(d) for d in db.scalars(
        select(NotificationDelivery).where(NotificationDelivery.alert_id == alert.id).order_by(NotificationDelivery.id)
    )]
    return data


@router.post("/{alert_id}/actions")
def act_on_alert(alert_id: str, body: AlertAction, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    alert = _get(db, alert_id, user)
    try:
        transition(db, alert, user, body.action, body.note)
    except TransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    db.commit()
    data = serialize_alert(alert, db)
    manager.broadcast_threadsafe({"type": "alert_updated", "alert": data}, user.organization_id)
    return data


@router.post("/bulk")
def bulk_action(ids: List[str], action: Literal["acknowledge", "resolve", "dismiss"], db: Session = Depends(get_db),
                user: User = Depends(require_operator)):
    if len(ids) > 200:
        raise HTTPException(status_code=422, detail="At most 200 alerts at a time.")
    done, skipped = [], []
    for alert_id in ids:
        alert = db.get(Alert, alert_id)
        if alert is None or alert.organization_id != user.organization_id:
            skipped.append(alert_id)
            continue
        try:
            transition(db, alert, user, action, None)
            done.append(alert_id)
        except TransitionError:
            skipped.append(alert_id)
    db.commit()
    manager.broadcast_threadsafe({"type": "alert_updated", "alert": None}, user.organization_id)
    return {"updated": done, "skipped": skipped}


@router.get("/{alert_id}/snapshot")
def alert_snapshot(alert_id: str, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    alert = _get(db, alert_id, user)
    path = snapshot_file(alert.snapshot_path) if alert.snapshot_status == "saved" else None
    if path is None:
        raise HTTPException(status_code=404, detail="No snapshot is available for this alert.")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
