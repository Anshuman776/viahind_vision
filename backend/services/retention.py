"""Data retention: purge old snapshots, optionally old event records, and closed alerts, per organization."""

import logging
import threading
from datetime import timedelta
from typing import Optional

from sqlalchemy import delete, select, update
from sqlalchemy.exc import SQLAlchemyError

from db import session_scope, utcnow
from models.entities import Alert, DetectionEvent, NotificationDelivery, Organization, SyncOutbox, Visit
from services.audit import record_audit
from services.site_settings import get_site_settings
from services.snapshots import delete_snapshot

logger = logging.getLogger("viahind.retention")

# Delivered notifications and synced outbox rows are only kept for troubleshooting.
DELIVERY_KEEP_DAYS = 30


def run_retention(organization_id: Optional[int] = None) -> dict:
    totals = {"purged_snapshots": 0, "deleted_events": 0, "deleted_visits": 0, "deleted_alerts": 0}
    with session_scope() as db:
        org_ids = [organization_id] if organization_id is not None else list(db.scalars(select(Organization.id)))
    for org_id in org_ids:
        result = _run_for_org(org_id)
        for k in totals:
            totals[k] += result[k]
    with session_scope() as db:
        cutoff = utcnow() - timedelta(days=DELIVERY_KEEP_DAYS)
        db.execute(delete(NotificationDelivery).where(NotificationDelivery.created_at < cutoff, NotificationDelivery.status != "pending"))
        db.execute(delete(SyncOutbox).where(SyncOutbox.status == "sent", SyncOutbox.sent_at < cutoff))
    return totals


def _run_for_org(org_id: int) -> dict:
    purged_snapshots = deleted_events = deleted_visits = deleted_alerts = 0
    with session_scope() as db:
        row = get_site_settings(db, org_id)
        now = utcnow()
        org = DetectionEvent.organization_id == org_id
        if row.snapshot_retention_days > 0:
            cutoff = now - timedelta(days=row.snapshot_retention_days)
            for event in db.scalars(select(DetectionEvent).where(org, DetectionEvent.occurred_at < cutoff, DetectionEvent.snapshot_status == "saved")):
                delete_snapshot(event.snapshot_path)
                event.snapshot_path = None
                event.snapshot_status = "purged"
                purged_snapshots += 1
            for alert in db.scalars(select(Alert).where(Alert.organization_id == org_id, Alert.first_seen_at < cutoff, Alert.snapshot_status == "saved")):
                delete_snapshot(alert.snapshot_path)
                alert.snapshot_path = None
                alert.snapshot_status = "purged"
                purged_snapshots += 1
        if row.event_retention_days > 0:
            cutoff = now - timedelta(days=row.event_retention_days)
            for event in db.scalars(select(DetectionEvent).where(org, DetectionEvent.occurred_at < cutoff)):
                delete_snapshot(event.snapshot_path)
            # Closed or voided visits that started before the cutoff go with their events;
            # visits still marked inside are kept so occupancy remains explainable.
            deleted_visits = db.execute(
                delete(Visit).where(Visit.organization_id == org_id, Visit.entry_at < cutoff, Visit.status.in_(("exited", "voided")))
            ).rowcount or 0
            db.execute(update(DetectionEvent).where(org, DetectionEvent.occurred_at < cutoff).values(visit_id=None))
            deleted_events = db.execute(delete(DetectionEvent).where(org, DetectionEvent.occurred_at < cutoff)).rowcount or 0
        if row.alert_retention_days > 0:
            cutoff = now - timedelta(days=row.alert_retention_days)
            closed = select(Alert).where(Alert.organization_id == org_id, Alert.status.in_(("resolved", "dismissed")), Alert.last_seen_at < cutoff)
            for alert in db.scalars(closed):
                delete_snapshot(alert.snapshot_path)
                db.delete(alert)
                deleted_alerts += 1
        if purged_snapshots or deleted_events or deleted_alerts:
            record_audit(
                db, None, "retention.run", "system", "retention",
                {"purged_snapshots": purged_snapshots, "deleted_events": deleted_events, "deleted_visits": deleted_visits, "deleted_alerts": deleted_alerts},
                organization_id=org_id,
            )
    return {"purged_snapshots": purged_snapshots, "deleted_events": deleted_events, "deleted_visits": deleted_visits, "deleted_alerts": deleted_alerts}


class RetentionScheduler:
    def __init__(self, interval_seconds: float = 3600):
        self.interval = interval_seconds
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="retention", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while True:
            try:
                result = run_retention()
                if any(result.values()):
                    logger.info("Retention: %s", result)
            except SQLAlchemyError:
                logger.exception("Retention run failed")
            if self._stop.wait(self.interval):
                return
