"""Data retention: purge old snapshots (and optionally old event records)."""

import logging
import threading
from datetime import timedelta
from typing import Optional

from sqlalchemy import delete, select, update
from sqlalchemy.exc import SQLAlchemyError

from db import session_scope, utcnow
from models.entities import DetectionEvent, Visit
from services.audit import record_audit
from services.site_settings import get_site_settings
from services.snapshots import delete_snapshot

logger = logging.getLogger("viahind.retention")


def run_retention() -> dict:
    purged_snapshots = deleted_events = deleted_visits = 0
    with session_scope() as db:
        row = get_site_settings(db)
        now = utcnow()
        if row.snapshot_retention_days > 0:
            cutoff = now - timedelta(days=row.snapshot_retention_days)
            old = db.scalars(
                select(DetectionEvent).where(DetectionEvent.occurred_at < cutoff, DetectionEvent.snapshot_status == "saved")
            ).all()
            for event in old:
                delete_snapshot(event.snapshot_path)
                event.snapshot_path = None
                event.snapshot_status = "purged"
                purged_snapshots += 1
        if row.event_retention_days > 0:
            cutoff = now - timedelta(days=row.event_retention_days)
            for event in db.scalars(select(DetectionEvent).where(DetectionEvent.occurred_at < cutoff)):
                delete_snapshot(event.snapshot_path)
            # Closed or voided visits that started before the cutoff go with their events;
            # visits still marked inside are kept so occupancy remains explainable.
            deleted_visits = db.execute(
                delete(Visit).where(Visit.entry_at < cutoff, Visit.status.in_(("exited", "voided")))
            ).rowcount or 0
            db.execute(update(DetectionEvent).where(DetectionEvent.occurred_at < cutoff).values(visit_id=None))
            deleted_events = db.execute(delete(DetectionEvent).where(DetectionEvent.occurred_at < cutoff)).rowcount or 0
        if purged_snapshots or deleted_events:
            record_audit(
                db, None, "retention.run", "system", "retention",
                {"purged_snapshots": purged_snapshots, "deleted_events": deleted_events, "deleted_visits": deleted_visits},
            )
    return {"purged_snapshots": purged_snapshots, "deleted_events": deleted_events, "deleted_visits": deleted_visits}


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
