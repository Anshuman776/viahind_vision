from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from auth import require_operator
from db import get_db, utcnow
from models.entities import DetectionEvent, User, Visit
from models.schemas import LinkExitRequest, VisitUpdate
from services.audit import audit_trail, record_audit
from services.events import LinkError, link_exit_to_visit, serialize_event, serialize_visit
from services.site_settings import get_site_settings, local_day_bounds

router = APIRouter(prefix="/visits", tags=["visits"])


@router.get("")
def list_visits(
    status: Optional[Literal["inside", "exited", "needs_review", "voided"]] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    q: Optional[str] = Query(None, max_length=64),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_operator),
):
    row = get_site_settings(db)
    stmt = select(Visit)
    if status:
        stmt = stmt.where(Visit.status == status)
    if date_from:
        stmt = stmt.where(Visit.entry_at >= local_day_bounds(row, date_from)[0])
    if date_to:
        stmt = stmt.where(Visit.entry_at < local_day_bounds(row, date_to)[1])
    if q:
        stmt = stmt.where(Visit.person_label.ilike(f"%{q.strip()}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Visit.entry_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [serialize_visit(v) for v in rows], "total": total, "page": page, "page_size": page_size}


def _get_visit(db: Session, visit_id: int) -> Visit:
    visit = db.get(Visit, visit_id)
    if visit is None:
        raise HTTPException(status_code=404, detail="Visit not found.")
    return visit


@router.get("/{visit_id}")
def get_visit(visit_id: int, db: Session = Depends(get_db), _: User = Depends(require_operator)):
    visit = _get_visit(db, visit_id)
    data = serialize_visit(visit)
    data["events"] = [
        serialize_event(e, db)
        for e in db.scalars(select(DetectionEvent).where(DetectionEvent.visit_id == visit.id).order_by(DetectionEvent.occurred_at))
    ]
    data["audit"] = audit_trail(db, "visit", visit.id)
    return data


@router.patch("/{visit_id}")
def update_visit(visit_id: int, body: VisitUpdate, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    visit = _get_visit(db, visit_id)
    if visit.status in ("exited", "voided") and body.status is not None:
        raise HTTPException(status_code=409, detail="Closed or voided visits cannot change status.")
    changes = {}
    if body.status is not None and body.status != visit.status:
        changes["status"] = [visit.status, body.status]
        visit.status = body.status
    if body.operator_note is not None:
        note = body.operator_note.strip() or None
        if note != visit.operator_note:
            changes["operator_note"] = [visit.operator_note, note]
            visit.operator_note = note
    if body.identified_by_operator is not None and body.identified_by_operator != visit.identified_by_operator:
        changes["identified_by_operator"] = [visit.identified_by_operator, body.identified_by_operator]
        visit.identified_by_operator = body.identified_by_operator
    if changes:
        visit.updated_at = utcnow()
        record_audit(db, user, "visit.update", "visit", visit.id, changes)
    db.commit()
    return serialize_visit(visit)


@router.post("/{visit_id}/link-exit")
def link_exit(visit_id: int, body: LinkExitRequest, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    visit = _get_visit(db, visit_id)
    event = db.get(DetectionEvent, body.event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Exit event not found.")
    try:
        link_exit_to_visit(db, visit, event, user)
    except LinkError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    db.commit()
    return serialize_visit(visit)
