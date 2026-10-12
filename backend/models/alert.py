from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum
from datetime import datetime

class AlertStatus(str, Enum):
    PENDING = "pending"
    ACKNOWLEDGED = "acknowledged"
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"

class AlertSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

class CameraModel(BaseModel):
    id: str
    name: str
    location: str
    floor: str
    rtsp_url: Optional[str] = None

class AIClassificationModel(BaseModel):
    label: str
    model_name: str
    model_version: str
    confidence_score: float
    threshold: float
    raw_log: str
    requires_human_verification: bool = True

class AlertReviewRequest(BaseModel):
    status: AlertStatus
    reviewer_notes: Optional[str] = None
    reviewer_id: Optional[str] = "security_officer_current"

class AlertResponse(BaseModel):
    id: str
    camera: CameraModel
    event_type: str
    severity: AlertSeverity
    status: AlertStatus
    timestamp: str
    detected_at_formatted: str
    ai_classification: AIClassificationModel
