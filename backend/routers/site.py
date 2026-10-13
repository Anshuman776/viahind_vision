from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth import get_current_user, require_admin
from config import settings
from db import get_db, utcnow
from models.entities import AuditLog, User
from models.schemas import SiteSettingsUpdate
from runtime import runtime
from services.audit import record_audit, serialize_audit
from services.retention import run_retention
from services.site_settings import get_site_settings
from services.snapshots import storage_status
from vision.detector import detector_availability

router = APIRouter(tags=["settings"])

EDITABLE = (
    "site_name", "timezone", "snapshot_retention_days", "event_retention_days", "min_confidence",
    "cooldown_seconds", "track_timeout_seconds", "min_track_hits", "min_side_frames", "line_band", "anchor_point",
)


def serialize_settings(row) -> dict:
    data = {field: getattr(row, field) for field in EDITABLE}
    data["updated_at"] = row.updated_at.isoformat()
    return data


@router.get("/settings")
def get_settings(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    row = get_site_settings(db)
    available, reason = detector_availability()
    return {
        "site": serialize_settings(row),
        "system": {
            "environment": settings.APP_ENV,
            "demo_mode": settings.IS_DEMO,
            "person_detector": {"available": available, "message": reason},
            "anomaly": runtime.anomaly.health_check() if runtime.anomaly else {"enabled": False, "status": "disabled"},
            "storage": storage_status(),
            "file_sources_allowed": settings.ALLOW_FILE_SOURCES,
            "test_video_dir": settings.TEST_VIDEO_DIR.name,
        },
    }


@router.put("/settings")
def update_settings(body: SiteSettingsUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    row = get_site_settings(db)
    changes = {}
    for field in EDITABLE:
        value = getattr(body, field)
        if value is not None and value != getattr(row, field):
            changes[field] = [getattr(row, field), value]
            setattr(row, field, value.strip() if isinstance(value, str) else value)
    if changes:
        row.updated_at = utcnow()
        record_audit(db, admin, "settings.update", "settings", 1, changes)
    db.commit()
    if runtime.cameras:
        runtime.cameras.refresh_params()
    return serialize_settings(row)


@router.post("/settings/retention/run")
def retention_now(admin: User = Depends(require_admin)):
    return run_retention()


@router.get("/audit")
def list_audit(limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db), _: User = Depends(require_admin)):
    rows = db.scalars(select(AuditLog).order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc()).limit(limit))
    return [serialize_audit(r) for r in rows]
