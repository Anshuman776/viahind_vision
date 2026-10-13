from fastapi import APIRouter, Depends, Query

from auth import require_operator
from models.entities import User
from runtime import runtime
from services.anomaly_store import list_anomaly_events

router = APIRouter(prefix="/anomaly", tags=["anomaly"])


@router.get("/status")
def anomaly_status(_: User = Depends(require_operator)):
    return runtime.anomaly.health_check() if runtime.anomaly else {"enabled": False, "status": "disabled"}


@router.get("/events")
def anomaly_events(limit: int = Query(50, ge=1, le=500), _: User = Depends(require_operator)):
    """Outputs recorded from the existing anomaly classifier. Empty unless it reports something."""
    return list_anomaly_events(limit=limit)
