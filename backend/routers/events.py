import csv
import io
from datetime import date
from typing import Iterator, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from auth import require_operator
from db import get_db
from models.entities import Camera, DetectionEvent, User, Visit
from models.schemas import EventUpdate
from services.audit import audit_trail, record_audit
from services.events import LinkError, serialize_event, serialize_visit, unlink_exit, update_event
from services.occupancy import compute_occupancy
from services.site_settings import get_site_settings, local_day_bounds, site_zone
from services.snapshots import snapshot_file
from websocket import manager

router = APIRouter(prefix="/events", tags=["events"])

EXPORT_LIMIT = 50000


def _filtered_query(
    db: Session,
    date_from: Optional[date],
    date_to: Optional[date],
    event_type: Optional[str],
    camera_id: Optional[str],
    q: Optional[str],
    review_status: Optional[str],
):
    row = get_site_settings(db)
    stmt = select(DetectionEvent)
    if date_from:
        stmt = stmt.where(DetectionEvent.occurred_at >= local_day_bounds(row, date_from)[0])
    if date_to:
        stmt = stmt.where(DetectionEvent.occurred_at < local_day_bounds(row, date_to)[1])
    if event_type:
        stmt = stmt.where(DetectionEvent.event_type == event_type)
    if camera_id:
        stmt = stmt.where(DetectionEvent.camera_id == camera_id)
    if review_status:
        stmt = stmt.where(DetectionEvent.review_status == review_status)
    if q:
        escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(DetectionEvent.person_label.ilike(f"%{escaped}%", escape="\\"))
    return stmt


EventType = Optional[Literal["entry", "exit", "uncertain"]]
ReviewStatus = Optional[Literal["auto", "needs_review", "confirmed", "corrected", "rejected"]]


@router.get("")
def list_events(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    event_type: EventType = None,
    camera_id: Optional[str] = Query(None, max_length=48),
    q: Optional[str] = Query(None, max_length=64),
    review_status: ReviewStatus = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_operator),
):
    stmt = _filtered_query(db, date_from, date_to, event_type, camera_id, q, review_status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(DetectionEvent.occurred_at.desc(), DetectionEvent.id).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return {"items": [serialize_event(e, db) for e in rows], "total": total, "page": page, "page_size": page_size}


def _csv_safe(value) -> str:
    """Neutralise spreadsheet formula injection."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


@router.get("/export.csv")
def export_events(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    event_type: EventType = None,
    camera_id: Optional[str] = Query(None, max_length=48),
    q: Optional[str] = Query(None, max_length=64),
    review_status: ReviewStatus = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_operator),
):
    stmt = _filtered_query(db, date_from, date_to, event_type, camera_id, q, review_status)
    rows = db.scalars(stmt.order_by(DetectionEvent.occurred_at.asc()).limit(EXPORT_LIMIT)).all()
    tz = site_zone(get_site_settings(db))
    cameras = {c.id: c.name for c in db.scalars(select(Camera))}
    record_audit(
        db, user, "events.export", "events", "csv",
        {"rows": len(rows), "filters": {"date_from": date_from, "date_to": date_to, "event_type": event_type, "camera_id": camera_id, "q": q, "review_status": review_status}},
    )
    db.commit()

    def generate() -> Iterator[str]:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["event_id", "date", "time", "timezone", "event", "person_label", "camera", "review_status", "visit_match", "confidence", "visit_id", "snapshot", "notes"])
        for e in rows:
            local = e.occurred_at.astimezone(tz)
            writer.writerow([
                e.id, local.date().isoformat(), local.strftime("%H:%M:%S"), str(tz), e.event_type,
                _csv_safe(e.person_label), _csv_safe(cameras.get(e.camera_id, e.camera_id)), e.review_status,
                e.match_status, "" if e.confidence is None else f"{e.confidence:.2f}", e.visit_id or "",
                "yes" if e.snapshot_status == "saved" else e.snapshot_status, _csv_safe(e.notes),
            ])
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)

    filename = f"viahind-events-{date_from or 'all'}-{date_to or 'all'}.csv"
    return StreamingResponse(
        generate(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "private, no-store"},
    )


def _get_event(db: Session, event_id: str) -> DetectionEvent:
    event = db.get(DetectionEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found.")
    return event


def _event_detail(db: Session, event: DetectionEvent) -> dict:
    data = serialize_event(event, db)
    visit = db.get(Visit, event.visit_id) if event.visit_id else None
    data["visit"] = serialize_visit(visit) if visit else None
    data["audit"] = audit_trail(db, "event", event.id)
    return data


@router.get("/{event_id}")
def get_event(event_id: str, db: Session = Depends(get_db), _: User = Depends(require_operator)):
    return _event_detail(db, _get_event(db, event_id))


@router.patch("/{event_id}")
def patch_event(event_id: str, body: EventUpdate, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    event = _get_event(db, event_id)
    update_event(db, event, user, event_type=body.event_type, review_status=body.review_status, notes=body.notes)
    db.commit()
    manager.broadcast_threadsafe({"type": "event_updated", "event": serialize_event(event, db), "occupancy": compute_occupancy(db)})
    return _event_detail(db, event)


@router.post("/{event_id}/unlink")
def unlink_event(event_id: str, db: Session = Depends(get_db), user: User = Depends(require_operator)):
    event = _get_event(db, event_id)
    try:
        unlink_exit(db, event, user)
    except LinkError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    db.commit()
    return _event_detail(db, event)


@router.get("/{event_id}/snapshot")
def get_snapshot(event_id: str, db: Session = Depends(get_db), _: User = Depends(require_operator)):
    event = _get_event(db, event_id)
    path = snapshot_file(event.snapshot_path) if event.snapshot_status == "saved" else None
    if path is None:
        raise HTTPException(status_code=404, detail="No snapshot is available for this event.")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
