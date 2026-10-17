"""Audit trail for operator actions (corrections, occupancy adjustments, settings, exports)."""

import json
from typing import Any, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.entities import AuditLog, User


def record_audit(
    db: Session,
    user: Optional[User],
    action: str,
    entity_type: str,
    entity_id: Any,
    details: Optional[dict] = None,
    organization_id: Optional[int] = None,
) -> AuditLog:
    """Add an audit entry to the current transaction (committed together with the change).

    The organization is the acting user's; system entries (user=None) pass organization_id.
    """
    entry = AuditLog(
        organization_id=user.organization_id if user else organization_id,
        user_id=user.id if user else None,
        username=user.username if user else "system",
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        details=json.dumps(details or {}, default=str, sort_keys=True),
    )
    db.add(entry)
    return entry


def audit_trail(db: Session, organization_id: int, entity_type: str, entity_id: Any, limit: int = 100) -> List[dict]:
    rows = db.scalars(
        select(AuditLog)
        .where(AuditLog.organization_id == organization_id, AuditLog.entity_type == entity_type, AuditLog.entity_id == str(entity_id))
        .order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc())
        .limit(limit)
    ).all()
    return [serialize_audit(r) for r in rows]


def serialize_audit(row: AuditLog) -> dict:
    return {
        "id": row.id,
        "occurred_at": row.occurred_at.isoformat(),
        "username": row.username,
        "action": row.action,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "details": json.loads(row.details or "{}"),
    }
