"""
Hybrid deployment: edge -> cloud event synchronisation.

Edge (DEPLOYMENT_MODE=edge)
- Every persisted event, and every later correction, adds a row to sync_outbox in the same
  transaction, so nothing is lost if the process stops. Payloads contain event metadata only:
  no images, no camera sources or credentials, no operator notes.
- SyncPusher sends pending rows in batches to SYNC_URL with the node's bearer token, and retries
  with bounded exponential backoff while the internet connection is down. Local recording and
  alerting continue unaffected.

Cloud (DEPLOYMENT_MODE=cloud)
- POST /api/v1/sync/events authenticates the node by token (stored as SHA-256), and upserts each
  event by its UUID. Re-sending the same batch is harmless (idempotent): an existing event is only
  updated when the incoming version is newer, and an event ID owned by another organization is rejected.
"""

import hashlib
import json
import logging
import secrets
import threading
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from config import settings
from db import session_scope, utcnow
from models.entities import DetectionEvent, SyncNode, SyncOutbox

logger = logging.getLogger("viahind.sync")

BACKOFF = (15, 60, 300, 900, 1800)
SYNC_FIELDS = ("id", "occurred_at", "event_type", "original_event_type", "person_label", "confidence",
               "review_status", "match_status", "uncertain_reason", "camera_id", "camera_name", "updated_at")
MUTABLE_FIELDS = ("event_type", "review_status", "match_status", "person_label")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token() -> str:
    return "vvn_" + secrets.token_urlsafe(32)


# -- edge -----------------------------------------------------------------------------------------

def event_payload(event: DetectionEvent) -> dict:
    return {
        "id": event.id,
        "occurred_at": event.occurred_at.isoformat(),
        "event_type": event.event_type,
        "original_event_type": event.original_event_type,
        "person_label": event.person_label,
        "confidence": event.confidence,
        "review_status": event.review_status,
        "match_status": event.match_status,
        "uncertain_reason": event.uncertain_reason,
        "camera_id": event.camera_id,
        "camera_name": event.camera.name if event.camera is not None else None,
        "updated_at": (event.updated_at or utcnow()).isoformat(),
    }


def enqueue_event(db: Session, event: DetectionEvent) -> None:
    if event.is_demo:
        return
    db.add(SyncOutbox(
        organization_id=event.organization_id, entity_type="event", entity_id=event.id,
        payload=json.dumps(event_payload(event), default=str), status="pending", next_attempt_at=utcnow(),
    ))


def outbox_status(db: Session, organization_id: int) -> dict:
    rows = dict(db.execute(
        select(SyncOutbox.status, func.count()).where(SyncOutbox.organization_id == organization_id).group_by(SyncOutbox.status)
    ).all())
    oldest = db.scalar(select(func.min(SyncOutbox.created_at)).where(SyncOutbox.organization_id == organization_id, SyncOutbox.status == "pending"))
    last_sent = db.scalar(select(func.max(SyncOutbox.sent_at)).where(SyncOutbox.organization_id == organization_id))
    last_error = db.scalar(select(SyncOutbox.last_error).where(SyncOutbox.organization_id == organization_id, SyncOutbox.status == "pending",
                                                              SyncOutbox.last_error.is_not(None)).order_by(SyncOutbox.id.desc()).limit(1))
    return {
        "mode": settings.DEPLOYMENT_MODE, "pending": rows.get("pending", 0), "sent": rows.get("sent", 0),
        "oldest_pending_at": oldest.isoformat() if oldest else None,
        "last_sent_at": last_sent.isoformat() if last_sent else None, "last_error": last_error,
    }


def push_once(send=None, batch_size: Optional[int] = None) -> Tuple[int, Optional[str]]:
    """Send one batch. Returns (rows sent, error). `send(batch) -> dict` defaults to HTTP."""
    send = send or _http_send
    batch_size = batch_size or settings.SYNC_BATCH_SIZE
    with session_scope() as db:
        rows = list(db.scalars(
            select(SyncOutbox).where(SyncOutbox.status == "pending", SyncOutbox.next_attempt_at <= utcnow())
            .order_by(SyncOutbox.id).limit(batch_size)
        ))
        batch = [{"outbox_id": r.id, **json.loads(r.payload)} for r in rows]
        ids = [r.id for r in rows]
    if not batch:
        return 0, None
    error = None
    accepted: set = set()
    try:
        result = send(batch)
        accepted = set(result.get("accepted", [])) | set(result.get("duplicates", []))
        rejected = {r["id"]: r.get("reason", "rejected") for r in result.get("rejected", [])}
    except Exception as exc:  # network failure: retry the whole batch later
        error = _safe_error(exc)
        rejected = {}
    with session_scope() as db:
        for row in db.scalars(select(SyncOutbox).where(SyncOutbox.id.in_(ids))):
            if row.entity_id in accepted:
                row.status, row.sent_at, row.last_error = "sent", utcnow(), None
            elif row.entity_id in rejected:
                row.status, row.last_error = "failed", str(rejected[row.entity_id])[:300]
            else:
                row.attempts += 1
                row.last_error = error or "Not acknowledged by the cloud."
                row.next_attempt_at = utcnow() + timedelta(seconds=BACKOFF[min(row.attempts - 1, len(BACKOFF) - 1)])
    return len(accepted), error


def _safe_error(exc: Exception) -> str:
    import httpx

    if isinstance(exc, httpx.HTTPStatusError):
        return f"Cloud answered HTTP {exc.response.status_code}."
    if isinstance(exc, httpx.HTTPError):
        return f"Cloud unreachable ({type(exc).__name__})."
    return type(exc).__name__


def _http_send(batch: List[dict]) -> dict:
    import httpx

    response = httpx.post(
        settings.SYNC_URL.rstrip("/") + "/api/v1/sync/events",
        json={"node_id": settings.SYNC_NODE_ID, "events": batch},
        headers={"Authorization": f"Bearer {settings.SYNC_TOKEN}"},
        timeout=20.0,
    )
    response.raise_for_status()
    return response.json()


class SyncPusher:
    def __init__(self, interval_seconds: Optional[float] = None):
        self.interval = interval_seconds or settings.SYNC_INTERVAL_SECONDS
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.last_error: Optional[str] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="sync-push", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                sent, self.last_error = push_once()
                while sent and not self.last_error and not self._stop.is_set():
                    sent, self.last_error = push_once()
            except SQLAlchemyError:
                logger.exception("Sync push failed (database)")


# -- cloud ----------------------------------------------------------------------------------------

def authenticate_node(db: Session, token: Optional[str]) -> Optional[SyncNode]:
    if not token:
        return None
    node = db.scalar(select(SyncNode).where(SyncNode.token_hash == hash_token(token)))
    if node is None or not node.enabled:
        return None
    return node


def _parse_time(value) -> datetime:
    dt = datetime.fromisoformat(str(value))
    if dt.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    return dt


def ingest_events(db: Session, node: SyncNode, events: List[dict]) -> dict:
    accepted, duplicates, rejected = [], [], []
    for item in events:
        event_id = str(item.get("id", ""))
        try:
            if len(event_id) != 36:
                raise ValueError("invalid id")
            if item.get("event_type") not in ("entry", "exit", "uncertain"):
                raise ValueError("invalid event_type")
            occurred = _parse_time(item["occurred_at"])
            updated = _parse_time(item.get("updated_at") or item["occurred_at"])
        except (KeyError, ValueError, TypeError) as exc:
            rejected.append({"id": event_id, "reason": str(exc)[:100]})
            continue
        existing = db.get(DetectionEvent, event_id)
        if existing is not None:
            if existing.organization_id != node.organization_id or existing.source_node_id != node.id:
                rejected.append({"id": event_id, "reason": "id belongs to another source"})
                continue
            if updated > existing.updated_at:
                for field in MUTABLE_FIELDS:
                    if item.get(field) is not None:
                        setattr(existing, field, str(item[field])[:48])
                existing.updated_at = updated
                accepted.append(event_id)
            else:
                duplicates.append(event_id)
            continue
        db.add(DetectionEvent(
            id=event_id, organization_id=node.organization_id, location_id=node.location_id, camera_id=None,
            occurred_at=occurred, event_type=item["event_type"],
            original_event_type=item.get("original_event_type") if item.get("original_event_type") in ("entry", "exit", "uncertain") else item["event_type"],
            person_label=str(item.get("person_label") or "Unknown Person")[:48],
            confidence=float(item["confidence"]) if isinstance(item.get("confidence"), (int, float)) else None,
            snapshot_status="none",
            review_status=item.get("review_status") if item.get("review_status") in ("auto", "needs_review", "confirmed", "corrected", "rejected") else "auto",
            match_status=item.get("match_status") if item.get("match_status") in ("not_applicable", "matched", "unmatched") else "not_applicable",
            uncertain_reason=(str(item["uncertain_reason"])[:64] if item.get("uncertain_reason") else None),
            source_node_id=node.id, source_camera_name=(str(item.get("camera_name") or item.get("camera_id") or "")[:120] or None),
            created_at=utcnow(), updated_at=updated,
        ))
        accepted.append(event_id)
    node.last_seen_at = utcnow()
    node.last_batch_size = len(events)
    db.flush()
    return {"accepted": accepted, "duplicates": duplicates, "rejected": rejected}


def serialize_node(node: SyncNode) -> dict:
    return {
        "id": node.id, "name": node.name, "location_id": node.location_id, "enabled": node.enabled,
        "last_seen_at": node.last_seen_at.isoformat() if node.last_seen_at else None,
        "last_batch_size": node.last_batch_size, "created_at": node.created_at.isoformat(),
    }
