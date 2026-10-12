from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
try:
    from ..models.alert import AlertResponse, AlertReviewRequest, AlertStatus
except ImportError:
    from models.alert import AlertResponse, AlertReviewRequest, AlertStatus

router = APIRouter(prefix="/alerts", tags=["alerts"])

@router.get("", response_model=List[AlertResponse])
async def list_alerts(
    status: Optional[str] = Query(None, description="Filter by pending/acknowledged/confirmed/dismissed"),
    severity: Optional[str] = Query(None, description="Filter by critical/high/medium/low"),
    floor: Optional[str] = Query(None, description="Filter by floor name"),
    search: Optional[str] = Query(None, description="Search query")
):
    """
    List security alerts with multi-criteria filtering.
    """
    # API-ready contract interface
    return []

@router.get("/{alert_id}", response_model=AlertResponse)
async def get_alert(alert_id: str):
    """
    Retrieve incident detail with video evidence URL, AI classifier output, and audit timeline.
    """
    raise HTTPException(status_code=404, detail="Alert not found")

@router.patch("/{alert_id}/review", response_model=AlertResponse)
async def review_alert(alert_id: str, review: AlertReviewRequest):
    """
    Transition alert status: acknowledge, confirm, or dismiss with optional reviewer notes.
    """
    raise HTTPException(status_code=404, detail="Alert not found")
