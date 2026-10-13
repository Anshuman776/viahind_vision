"""
Entry/exit event recording, visit matching and operator corrections.

Matching rules (deliberately conservative):
- An entry opens a visit for the track's pseudonymous label.
- An exit closes a visit automatically ONLY when the same tracker track (same camera worker
  session) produced that visit's entry. Tracker continuity is the only automatic link.
- Any other exit is recorded as "unmatched": it still counts toward occupancy, but no visit
  is closed and no duration is shown until an operator links it.
- Events are never paired just because their timestamps are close.
"""

import logging
import threading
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Deque, List, Optional

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from db import session_scope, utcnow
from models.entities import Camera, DetectionEvent, PersonTrack, User, Visit
from services.audit import record_audit
from services.site_settings import allocate_person_label
from services.snapshots import delete_snapshot, save_snapshot
from vision.line_crossing import CrossingEvent

logger = logging.getLogger("viahind.events")

# Serialises label allocation and visit matching within this process.
_record_lock = threading.Lock()


@dataclass
class PendingEvent:
    camera_id: str
    session_id: str
    crossing: CrossingEvent
    event_id: str
    snapshot_path: Optional[str]
    snapshot_status: str
    attempts: int = 0


class EventRecorder:
    """Persists crossing events from camera workers.

    An event is reported as recorded (and broadcast) only after the database commit succeeds.
    On database failure the event is held in a bounded retry queue and retried in the background.
    """

    def __init__(self, on_recorded: Optional[Callable[[dict], None]] = None, max_pending: int = 500):
        self.on_recorded = on_recorded
        self._pending: Deque[PendingEvent] = deque(maxlen=max_pending)
        self._pending_lock = threading.Lock()
        self.dropped_pending = 0
        self.last_db_error: Optional[str] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # -- worker-facing API ----------------------------------------------------------------
    def record(self, camera_id: str, session_id: str, crossing: CrossingEvent, snapshot_jpeg: Optional[bytes]) -> Optional[dict]:
        event_id = str(uuid.uuid4())
        occurred = datetime.fromtimestamp(crossing.occurred_at, tz=timezone.utc)
        rel, snap_status = save_snapshot(event_id, occurred, snapshot_jpeg)
        pending = PendingEvent(camera_id, session_id, crossing, event_id, rel, snap_status)
        return self._try_persist(pending)

    def pending_count(self) -> int:
        with self._pending_lock:
            return len(self._pending)

    def start_retry_loop(self, interval: float = 5.0) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._retry_loop, args=(interval,), name="event-retry", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def retry_pending(self) -> int:
        """Retry queued events once, oldest first. Returns how many were persisted."""
        persisted = 0
        while True:
            with self._pending_lock:
                if not self._pending:
                    return persisted
                item = self._pending.popleft()
            if self._try_persist(item, requeue_front=True) is None:
                return persisted
            persisted += 1

    # -- internals ------------------------------------------------------------------------
    def _retry_loop(self, interval: float) -> None:
        while not self._stop.wait(interval):
            if self.pending_count():
                self.retry_pending()

    def _try_persist(self, item: PendingEvent, requeue_front: bool = False) -> Optional[dict]:
        try:
            with _record_lock, session_scope() as db:
                payload = persist_crossing(db, item)
        except SQLAlchemyError as exc:
            item.attempts += 1
            self.last_db_error = type(exc).__name__
            logger.error("Database write failed for event %s (%s); queued for retry", item.event_id, type(exc).__name__)
            with self._pending_lock:
                if len(self._pending) == self._pending.maxlen:
                    dropped = self._pending.popleft()
                    self.dropped_pending += 1
                    delete_snapshot(dropped.snapshot_path)
                    logger.error("Retry queue full: event %s was lost", dropped.event_id)
                if requeue_front:
                    self._pending.appendleft(item)
                else:
                    self._pending.append(item)
            return None
        self.last_db_error = None
        if self.on_recorded is not None:
            try:
                self.on_recorded(payload)
            except Exception:
                logger.exception("Event broadcast failed")
        return payload


def persist_crossing(db: Session, item: PendingEvent) -> dict:
    crossing = item.crossing
    occurred = datetime.fromtimestamp(crossing.occurred_at, tz=timezone.utc)

    track = db.scalar(
        select(PersonTrack).where(
            PersonTrack.camera_id == item.camera_id,
            PersonTrack.session_id == item.session_id,
            PersonTrack.tracker_id == crossing.track_id,
        )
    )
    if track is None:
        track = PersonTrack(
            camera_id=item.camera_id,
            session_id=item.session_id,
            tracker_id=crossing.track_id,
            person_label=allocate_person_label(db),
            first_seen_at=occurred,
            last_seen_at=occurred,
        )
        db.add(track)
        db.flush()
    else:
        track.last_seen_at = max(track.last_seen_at, occurred)

    event = DetectionEvent(
        id=item.event_id,
        camera_id=item.camera_id,
        occurred_at=occurred,
        event_type=crossing.event_type,
        original_event_type=crossing.event_type,
        person_label=track.person_label,
        track_id=track.id,
        confidence=crossing.confidence,
        snapshot_path=item.snapshot_path,
        snapshot_status=item.snapshot_status,
        review_status="needs_review" if crossing.event_type == "uncertain" else "auto",
        uncertain_reason=crossing.reason,
    )
    db.add(event)
    db.flush()

    if crossing.event_type == "entry":
        _open_visit(db, event, match_method="tracker")
    elif crossing.event_type == "exit":
        visit = db.scalar(
            select(Visit)
            .join(DetectionEvent, DetectionEvent.id == Visit.entry_event_id)
            .where(
                DetectionEvent.track_id == track.id,
                Visit.status == "inside",
                Visit.exit_event_id.is_(None),
            )
            .order_by(Visit.entry_at.desc())
        )
        if visit is not None:
            _close_visit(visit, event, match_method="tracker")
        else:
            event.match_status = "unmatched"
    db.flush()
    return serialize_event(event, db)


def _open_visit(db: Session, event: DetectionEvent, match_method: Optional[str]) -> Visit:
    visit = Visit(
        person_label=event.person_label,
        entry_event_id=event.id,
        entry_at=event.occurred_at,
        entry_camera_id=event.camera_id,
        status="inside",
        match_method=match_method,
    )
    db.add(visit)
    db.flush()
    event.visit_id = visit.id
    event.match_status = "not_applicable"
    return visit


def _close_visit(visit: Visit, event: DetectionEvent, match_method: str) -> None:
    visit.exit_event_id = event.id
    visit.exit_at = event.occurred_at
    visit.exit_camera_id = event.camera_id
    visit.status = "exited"
    visit.match_method = match_method
    visit.updated_at = utcnow()
    event.visit_id = visit.id
    event.match_status = "matched"


# -- operator corrections ------------------------------------------------------------------

def _detach(db: Session, event: DetectionEvent) -> None:
    """Undo the visit effects of an event's current type."""
    if event.visit_id is not None:
        visit = db.get(Visit, event.visit_id)
        if visit is not None:
            if visit.entry_event_id == event.id:
                if visit.exit_event_id:
                    exit_event = db.get(DetectionEvent, visit.exit_event_id)
                    if exit_event is not None:
                        exit_event.visit_id = None
                        exit_event.match_status = "unmatched"
                visit.status = "voided"
            elif visit.exit_event_id == event.id:
                visit.exit_event_id = None
                visit.exit_at = None
                visit.exit_camera_id = None
                visit.status = "inside"
                if visit.match_method == "manual":
                    visit.match_method = None
            visit.updated_at = utcnow()
        event.visit_id = None
    event.match_status = "not_applicable"


def _attach(db: Session, event: DetectionEvent) -> None:
    """Apply the visit effects of an event's current type."""
    if event.event_type == "entry":
        _open_visit(db, event, match_method=None)
    elif event.event_type == "exit":
        event.match_status = "unmatched"


def update_event(
    db: Session,
    event: DetectionEvent,
    user: User,
    event_type: Optional[str] = None,
    review_status: Optional[str] = None,
    notes: Optional[str] = None,
) -> DetectionEvent:
    before = {"event_type": event.event_type, "review_status": event.review_status, "notes": event.notes, "visit_id": event.visit_id}
    was_rejected = event.review_status == "rejected"

    if review_status == "rejected" and not was_rejected:
        _detach(db, event)
        event.review_status = "rejected"
    elif was_rejected and review_status in ("confirmed", "needs_review"):
        event.review_status = review_status
        if event_type and event_type != event.event_type:
            event.event_type = event_type
            event.review_status = "corrected"
        _attach(db, event)
    else:
        if event_type and event_type != event.event_type and event.review_status != "rejected":
            _detach(db, event)
            event.event_type = event_type
            _attach(db, event)
            event.review_status = "corrected"
        elif review_status and review_status != "rejected":
            event.review_status = review_status
    if notes is not None:
        event.notes = notes.strip() or None

    event.updated_at = utcnow()
    db.flush()
    after = {"event_type": event.event_type, "review_status": event.review_status, "notes": event.notes, "visit_id": event.visit_id}
    if before != after:
        record_audit(db, user, "event.update", "event", event.id, {"before": before, "after": after})
    return event


class LinkError(ValueError):
    pass


def link_exit_to_visit(db: Session, visit: Visit, event: DetectionEvent, user: User) -> None:
    if event.event_type != "exit" or event.review_status == "rejected":
        raise LinkError("Only a valid exit event can be linked to a visit.")
    if event.visit_id is not None:
        raise LinkError("This exit is already linked to a visit. Unlink it first.")
    if visit.status not in ("inside", "needs_review") or visit.exit_event_id is not None:
        raise LinkError("The visit is not open.")
    if visit.entry_at is None or event.occurred_at < visit.entry_at:
        raise LinkError("The exit happened before the visit's entry.")
    previous_label = event.person_label
    _close_visit(visit, event, match_method="manual")
    event.person_label = visit.person_label
    event.updated_at = utcnow()
    record_audit(
        db, user, "visit.link_exit", "visit", visit.id,
        {"exit_event_id": event.id, "previous_event_label": previous_label, "label": visit.person_label},
    )
    record_audit(db, user, "event.linked_to_visit", "event", event.id, {"visit_id": visit.id, "previous_label": previous_label})


def unlink_exit(db: Session, event: DetectionEvent, user: User) -> None:
    if event.event_type != "exit" or event.visit_id is None:
        raise LinkError("This event is not a linked exit.")
    visit_id = event.visit_id
    _detach(db, event)
    event.match_status = "unmatched"
    if event.track_id is not None:
        track = db.get(PersonTrack, event.track_id)
        if track is not None:
            event.person_label = track.person_label
    event.updated_at = utcnow()
    record_audit(db, user, "event.unlink_exit", "event", event.id, {"visit_id": visit_id})


# -- serialisation ---------------------------------------------------------------------------

def serialize_event(event: DetectionEvent, db: Optional[Session] = None, camera_name: Optional[str] = None) -> dict:
    if camera_name is None and event.camera_id:
        cam = event.camera if event.camera is not None else (db.get(Camera, event.camera_id) if db else None)
        camera_name = cam.name if cam else event.camera_id
    return {
        "id": event.id,
        "camera_id": event.camera_id,
        "camera_name": camera_name,
        "occurred_at": event.occurred_at.isoformat(),
        "event_type": event.event_type,
        "original_event_type": event.original_event_type,
        "person_label": event.person_label,
        "visit_id": event.visit_id,
        "confidence": event.confidence,
        "has_snapshot": event.snapshot_status == "saved" and bool(event.snapshot_path),
        "snapshot_status": event.snapshot_status,
        "review_status": event.review_status,
        "match_status": event.match_status,
        "uncertain_reason": event.uncertain_reason,
        "notes": event.notes,
        "is_demo": event.is_demo,
    }


def serialize_visit(visit: Visit) -> dict:
    reliable = visit.match_method in ("tracker", "manual") and visit.entry_at is not None and visit.exit_at is not None
    return {
        "id": visit.id,
        "person_label": visit.person_label,
        "status": visit.status,
        "entry_event_id": visit.entry_event_id,
        "exit_event_id": visit.exit_event_id,
        "entry_at": visit.entry_at.isoformat() if visit.entry_at else None,
        "exit_at": visit.exit_at.isoformat() if visit.exit_at else None,
        "entry_camera_id": visit.entry_camera_id,
        "exit_camera_id": visit.exit_camera_id,
        "match_method": visit.match_method,
        "duration_seconds": int((visit.exit_at - visit.entry_at).total_seconds()) if reliable else None,
        "operator_note": visit.operator_note,
        "identified_by_operator": visit.identified_by_operator,
    }


def list_open_visits(db: Session, limit: int = 100) -> List[Visit]:
    return list(
        db.scalars(
            select(Visit).where(Visit.status.in_(("inside", "needs_review"))).order_by(Visit.entry_at.desc()).limit(limit)
        ).all()
    )
