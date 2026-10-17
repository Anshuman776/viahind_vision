"""
Alert persistence, deduplication and the human review workflow.

- An alert is identified by a dedup key (rule + subject, e.g. "camera_offline:CAM-1").
  While an alert with that key is open (new / acknowledged), further occurrences update it
  (occurrence count, last seen, latest metrics) instead of creating new alerts.
- Notifications are queued when an alert is created, and again for an ongoing alert only after
  the rule's cooldown has elapsed (or when its severity increases).
- Review statuses: new -> acknowledged -> resolved | dismissed. Resolved/dismissed alerts are
  closed; a later occurrence creates a new alert.
"""

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from db import utcnow
from models.entities import ALERT_SEVERITIES, OPEN_ALERT_STATUSES, Alert, Camera, CameraZone, Location, User
from services.audit import record_audit

logger = logging.getLogger("viahind.alerts")

SEVERITY_RANK = {s: i for i, s in enumerate(ALERT_SEVERITIES)}

# Called after commit with (organization_id, serialized alert, notify) — set by main.py.
on_alert_changed: Optional[Callable[[int, dict, bool], None]] = None
# Head guard hook (services/head_guard.on_report), set by main.py: (db, alert, created, notify) -> handled.
# When it returns True the head guard owns owner notifications for this alert (one message per incident).
report_hook: Optional[Callable[[Session, "Alert", bool, bool], bool]] = None


@dataclass
class AlertDraft:
    organization_id: int
    rule_type: str
    category: str
    severity: str
    title: str
    reason: str
    dedup_key: str
    occurred_at: datetime
    metrics: Optional[dict] = None
    location_id: Optional[int] = None
    camera_id: Optional[str] = None
    zone_id: Optional[int] = None
    event_id: Optional[str] = None
    track_label: Optional[str] = None
    model_score: Optional[float] = None
    snapshot_path: Optional[str] = None
    snapshot_status: str = "none"


@dataclass
class AlertOutcome:
    alert: Alert
    created: bool
    notify: bool


def raise_alert(db: Session, draft: AlertDraft, cooldown_seconds: int) -> AlertOutcome:
    """Create or update an alert. Caller commits, then calls publish()."""
    existing = db.scalar(
        select(Alert)
        .where(
            Alert.organization_id == draft.organization_id,
            Alert.dedup_key == draft.dedup_key,
            Alert.status.in_(OPEN_ALERT_STATUSES),
        )
        .order_by(Alert.last_seen_at.desc())
        .limit(1)
    )
    now = utcnow()
    if existing is not None:
        existing.occurrences += 1
        existing.last_seen_at = max(existing.last_seen_at, draft.occurred_at)
        metrics = dict(draft.metrics or {})
        if existing.snapshot_status == "saved":
            # Keep the reason that matches the stored evidence; record the latest occurrence separately.
            metrics["latest_occurrence"] = draft.reason
        else:
            existing.reason = draft.reason
        existing.metrics = json.dumps(metrics, default=str, sort_keys=True)
        escalated = SEVERITY_RANK.get(draft.severity, 0) > SEVERITY_RANK.get(existing.severity, 0)
        if escalated:
            existing.severity = draft.severity
        if existing.snapshot_status != "saved" and draft.snapshot_status == "saved":
            existing.snapshot_path, existing.snapshot_status = draft.snapshot_path, draft.snapshot_status
        cooled = existing.last_notified_at is None or now - existing.last_notified_at >= timedelta(seconds=cooldown_seconds)
        notify = escalated or cooled
        if notify:
            existing.last_notified_at = now
        existing.updated_at = now
        return AlertOutcome(existing, False, notify)

    alert = Alert(
        id=str(uuid.uuid4()),
        organization_id=draft.organization_id,
        location_id=draft.location_id,
        camera_id=draft.camera_id,
        zone_id=draft.zone_id,
        rule_type=draft.rule_type,
        category=draft.category,
        severity=draft.severity,
        title=draft.title[:200],
        reason=draft.reason,
        metrics=json.dumps(draft.metrics or {}, default=str, sort_keys=True),
        model_score=draft.model_score,
        event_id=draft.event_id,
        track_label=draft.track_label,
        snapshot_path=draft.snapshot_path,
        snapshot_status=draft.snapshot_status,
        status="new",
        dedup_key=draft.dedup_key[:200],
        occurrences=1,
        first_seen_at=draft.occurred_at,
        last_seen_at=draft.occurred_at,
        last_notified_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(alert)
    db.flush()
    return AlertOutcome(alert, True, True)


def publish(db: Session, outcome: AlertOutcome) -> None:
    """After commit: queue notifications and push to signed-in users of the organization."""
    alert = outcome.alert
    handled = False
    if report_hook is not None:
        handled = report_hook(db, alert, outcome.created, outcome.notify)
    if outcome.notify and not handled:
        from services.notifications import queue_alert_notifications

        try:
            queue_alert_notifications(db, alert)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Could not queue notifications for alert %s", alert.id)
    if on_alert_changed is not None:
        try:
            on_alert_changed(alert.organization_id, serialize_alert(alert, db), outcome.created)
        except Exception:
            logger.exception("Alert broadcast failed")


def auto_resolve(db: Session, organization_id: int, dedup_key: str, note: str) -> List[Alert]:
    """Close open system alerts whose condition has cleared (camera back online, etc.)."""
    now = utcnow()
    rows = list(db.scalars(select(Alert).where(
        Alert.organization_id == organization_id, Alert.dedup_key == dedup_key, Alert.status.in_(OPEN_ALERT_STATUSES)
    )))
    for alert in rows:
        alert.status = "resolved"
        alert.resolved_by = "system"
        alert.resolved_at = now
        alert.resolution_note = note
        alert.updated_at = now
    return rows


class TransitionError(ValueError):
    pass


ALLOWED = {
    "acknowledge": ({"new"}, "acknowledged"),
    "resolve": ({"new", "acknowledged"}, "resolved"),
    "dismiss": ({"new", "acknowledged"}, "dismissed"),
    "reopen": ({"resolved", "dismissed"}, "acknowledged"),
}


def transition(db: Session, alert: Alert, user: User, action: str, note: Optional[str]) -> Alert:
    if action not in ALLOWED:
        raise TransitionError("Unknown action.")
    sources, target = ALLOWED[action]
    if alert.status not in sources:
        raise TransitionError(f"An alert that is {alert.status} cannot be {target}.")
    before = alert.status
    now = utcnow()
    alert.status = target
    if target == "acknowledged":
        alert.acknowledged_by, alert.acknowledged_at = user.username, now
        if action == "reopen":
            alert.resolved_by = alert.resolved_at = None
    if target in ("resolved", "dismissed"):
        alert.resolved_by, alert.resolved_at = user.username, now
        if not alert.acknowledged_at:
            alert.acknowledged_by, alert.acknowledged_at = user.username, now
    if note is not None and note.strip():
        alert.resolution_note = note.strip()[:2000]
    alert.updated_at = now
    record_audit(db, user, f"alert.{action}", "alert", alert.id, {"before": before, "after": target, "note": alert.resolution_note})
    return alert


def serialize_alert(alert: Alert, db: Optional[Session] = None, include_snapshot: bool = True) -> dict:
    camera_name = location_name = zone_name = None
    if db is not None:
        if alert.camera_id:
            cam = db.get(Camera, alert.camera_id)
            camera_name = cam.name if cam else alert.camera_id
        if alert.location_id:
            loc = db.get(Location, alert.location_id)
            location_name = loc.name if loc else None
        if alert.zone_id:
            zone = db.get(CameraZone, alert.zone_id)
            zone_name = zone.name if zone else None
    try:
        metrics = json.loads(alert.metrics or "{}")
    except json.JSONDecodeError:
        metrics = {}
    return {
        "id": alert.id,
        "rule_type": alert.rule_type,
        "category": alert.category,
        "severity": alert.severity,
        "title": alert.title,
        "reason": alert.reason,
        "metrics": metrics,
        "model_score": alert.model_score,
        "location_id": alert.location_id,
        "location_name": location_name,
        "camera_id": alert.camera_id,
        "camera_name": camera_name,
        "zone_id": alert.zone_id,
        "zone_name": zone_name,
        "event_id": alert.event_id,
        "track_label": alert.track_label,
        "has_snapshot": include_snapshot and alert.snapshot_status == "saved" and bool(alert.snapshot_path),
        "snapshot_status": alert.snapshot_status,
        "status": alert.status,
        "occurrences": alert.occurrences,
        "first_seen_at": alert.first_seen_at.isoformat(),
        "last_seen_at": alert.last_seen_at.isoformat(),
        "acknowledged_by": alert.acknowledged_by,
        "acknowledged_at": alert.acknowledged_at.isoformat() if alert.acknowledged_at else None,
        "resolved_by": alert.resolved_by,
        "resolved_at": alert.resolved_at.isoformat() if alert.resolved_at else None,
        "resolution_note": alert.resolution_note,
    }
