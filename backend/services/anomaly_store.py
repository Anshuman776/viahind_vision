"""Persistence for anomaly classifier outputs received through vision/anomaly.py."""

import json
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select

from db import session_scope
from models.entities import AnomalyEvent
from vision.anomaly import AnomalyResult


def store_anomaly(result: AnomalyResult) -> dict:
    with session_scope() as db:
        row = AnomalyEvent(
            camera_id=result.camera_id,
            occurred_at=datetime.fromtimestamp(result.occurred_at, tz=timezone.utc),
            label=result.label,
            confidence=result.confidence,
            model_name=result.model_name,
            model_version=result.model_version,
            raw_output=json.dumps(result.raw_output),
        )
        db.add(row)
        db.flush()
        return serialize_anomaly(row)


def list_anomaly_events(since: Optional[datetime] = None, limit: int = 50) -> List[dict]:
    with session_scope() as db:
        q = select(AnomalyEvent).order_by(AnomalyEvent.occurred_at.desc()).limit(min(limit, 500))
        if since is not None:
            q = q.where(AnomalyEvent.occurred_at >= since)
        return [serialize_anomaly(r) for r in db.scalars(q)]


def serialize_anomaly(row: AnomalyEvent) -> dict:
    return {
        "id": row.id,
        "camera_id": row.camera_id,
        "occurred_at": row.occurred_at.isoformat(),
        "label": row.label,
        "confidence": row.confidence,
        "model_name": row.model_name,
        "model_version": row.model_version,
        "review_status": row.review_status,
    }
