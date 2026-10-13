from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth import require_operator
from db import get_db
from models.entities import DetectionEvent, OccupancySnapshot, User
from models.schemas import AdjustRequest, ReconcileRequest
from services import occupancy as occupancy_service
from services.events import serialize_event
from services.stats import day_summary
from websocket import manager

router = APIRouter(tags=["overview"])


@router.get("/overview")
def overview(db: Session = Depends(get_db), _: User = Depends(require_operator)):
    """Everything the Overview page needs, from persisted records only."""
    recent = db.scalars(select(DetectionEvent).order_by(DetectionEvent.occurred_at.desc()).limit(10)).all()
    return {
        "occupancy": occupancy_service.compute_occupancy(db),
        "today": day_summary(db),
        "recent_events": [serialize_event(e, db) for e in recent],
    }


@router.get("/stats/daily")
def daily(day: Optional[date] = Query(None), db: Session = Depends(get_db), _: User = Depends(require_operator)):
    return day_summary(db, day)


@router.get("/occupancy")
def get_occupancy(db: Session = Depends(get_db), _: User = Depends(require_operator)):
    return occupancy_service.compute_occupancy(db)


@router.get("/occupancy/history")
def occupancy_history(db: Session = Depends(get_db), _: User = Depends(require_operator)):
    rows = db.scalars(select(OccupancySnapshot).order_by(OccupancySnapshot.recorded_at.desc()).limit(50)).all()
    return [
        {"id": r.id, "kind": r.kind, "value": r.value, "reason": r.reason, "recorded_at": r.recorded_at.isoformat(), "user_id": r.user_id}
        for r in rows
    ]


def _after_change(db: Session) -> dict:
    db.commit()
    result = occupancy_service.compute_occupancy(db)
    manager.broadcast_threadsafe({"type": "occupancy", "occupancy": result})
    return result


@router.post("/occupancy/reconcile")
def reconcile(body: ReconcileRequest, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    try:
        occupancy_service.reconcile(db, user, body.count, body.reason)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _after_change(db)


@router.post("/occupancy/adjust")
def adjust(body: AdjustRequest, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    try:
        occupancy_service.adjust(db, user, body.delta, body.reason)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _after_change(db)
