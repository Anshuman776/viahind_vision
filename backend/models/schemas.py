"""Request validation schemas for the surveillance API."""

import re
from typing import Dict, List, Literal, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator

CAMERA_ID = re.compile(r"^[A-Z0-9][A-Z0-9\-]{1,47}$")
USERNAME = re.compile(r"^[a-zA-Z0-9_.\-]{3,64}$")


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class CameraCreate(BaseModel):
    id: str = Field(description="Camera identifier, e.g. CAM-ENTRANCE-01")
    name: str = Field(min_length=1, max_length=120)
    location: str = Field(default="", max_length=160)
    source_type: Literal["browser", "device", "network", "file"]
    # Write-only. Never returned by the API.
    source: Optional[str] = Field(default=None, max_length=2048)
    detection_enabled: bool = True
    counting_enabled: bool = True
    # Defaults to the organization's first location.
    location_id: Optional[int] = None

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        v = v.strip().upper()
        if not CAMERA_ID.match(v):
            raise ValueError("Use 2-48 characters: capital letters, digits and hyphens (e.g. CAM-ENTRANCE-01).")
        return v

    @field_validator("name", "location")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class CameraUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    location: Optional[str] = Field(default=None, max_length=160)
    source_type: Optional[Literal["browser", "device", "network", "file"]] = None
    # Omit to keep the stored source; send a value to replace it.
    source: Optional[str] = Field(default=None, max_length=2048)
    enabled: Optional[bool] = None
    detection_enabled: Optional[bool] = None
    counting_enabled: Optional[bool] = None
    location_id: Optional[int] = None


class SourceTest(BaseModel):
    source_type: Literal["device", "network", "file"]
    source: str = Field(min_length=1, max_length=2048)


class ZoneBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["restricted", "monitored"] = "monitored"
    polygon: List[List[float]] = Field(min_length=3, max_length=32)
    dwell_seconds: Optional[float] = Field(default=None, ge=5, le=86400)
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @field_validator("polygon")
    @classmethod
    def _polygon(cls, v: List[List[float]]) -> List[List[float]]:
        for point in v:
            if len(point) != 2 or not all(0.0 <= c <= 1.0 for c in point):
                raise ValueError("Zone points are [x, y] pairs between 0 and 1.")
        xs, ys = [p[0] for p in v], [p[1] for p in v]
        area = 0.5 * abs(sum(xs[i] * ys[i - 1] - xs[i - 1] * ys[i] for i in range(len(v))))
        if area < 0.0025:
            raise ValueError("The zone is too small; draw it over the area to watch.")
        return [[round(p[0], 4), round(p[1], 4)] for p in v]

    @model_validator(mode="after")
    def _monitored_needs_dwell(self):
        if self.kind == "monitored" and self.dwell_seconds is None:
            raise ValueError("A monitored zone needs a dwell threshold (seconds); use a restricted zone to alert on any presence.")
        return self


class LocationBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    address: str = Field(default="", max_length=255)
    capacity: Optional[int] = Field(default=None, ge=1, le=100000)
    business_hours: Optional[Dict[str, List[List[str]]]] = None
    is_active: bool = True

    @field_validator("name", "address")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class LocationUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    address: Optional[str] = Field(default=None, max_length=255)
    capacity: Optional[int] = Field(default=None, ge=1, le=100000)
    clear_capacity: bool = False
    business_hours: Optional[Dict[str, List[List[str]]]] = None
    clear_business_hours: bool = False
    is_active: Optional[bool] = None


class AlertAction(BaseModel):
    action: Literal["acknowledge", "resolve", "dismiss", "reopen"]
    note: Optional[str] = Field(default=None, max_length=2000)


class RuleUpdate(BaseModel):
    enabled: Optional[bool] = None
    severity: Optional[Literal["info", "low", "medium", "high", "critical"]] = None
    cooldown_seconds: Optional[int] = Field(default=None, ge=0, le=86400)
    params: Optional[Dict[str, object]] = None


class ChannelBody(BaseModel):
    kind: Literal["email", "webhook", "telegram"]
    name: str = Field(min_length=1, max_length=80)
    enabled: bool = True
    min_severity: Literal["info", "low", "medium", "high", "critical"] = "medium"
    categories: Optional[List[str]] = None
    rate_limit_per_hour: int = Field(default=30, ge=1, le=1000)
    # Write-only configuration
    recipients: Optional[List[str]] = Field(default=None, max_length=20)
    url: Optional[str] = Field(default=None, max_length=2048)
    secret: Optional[str] = Field(default=None, max_length=256)
    bot_token: Optional[str] = Field(default=None, max_length=100)
    chat_id: Optional[str] = Field(default=None, max_length=64)
    # Opt-in: attach the alert's evidence snapshot (email and Telegram).
    attach_snapshot: Optional[bool] = None


class ChannelUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    enabled: Optional[bool] = None
    min_severity: Optional[Literal["info", "low", "medium", "high", "critical"]] = None
    categories: Optional[List[str]] = None
    clear_categories: bool = False
    rate_limit_per_hour: Optional[int] = Field(default=None, ge=1, le=1000)
    recipients: Optional[List[str]] = Field(default=None, max_length=20)
    url: Optional[str] = Field(default=None, max_length=2048)
    secret: Optional[str] = Field(default=None, max_length=256)
    bot_token: Optional[str] = Field(default=None, max_length=100)
    chat_id: Optional[str] = Field(default=None, max_length=64)
    attach_snapshot: Optional[bool] = None


class ScheduleBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    frequency: Literal["daily", "weekly", "monthly"]
    location_id: Optional[int] = None
    channel_id: int
    enabled: bool = True


class TrainRequest(BaseModel):
    days: int = Field(default=60, ge=7, le=180)
    contamination: float = Field(default=0.01, ge=0.001, le=0.1)


class SyncNodeCreate(BaseModel):
    id: str = Field(min_length=3, max_length=48, pattern=r"^[A-Za-z0-9][A-Za-z0-9\-_]{2,47}$")
    name: str = Field(min_length=1, max_length=120)
    location_id: int


class LineUpdate(BaseModel):
    x1: float = Field(ge=0, le=1)
    y1: float = Field(ge=0, le=1)
    x2: float = Field(ge=0, le=1)
    y2: float = Field(ge=0, le=1)
    entry_side: Literal[1, -1] = 1

    @model_validator(mode="after")
    def _length(self):
        if ((self.x2 - self.x1) ** 2 + (self.y2 - self.y1) ** 2) ** 0.5 < 0.05:
            raise ValueError("The entrance line is too short; draw it across the doorway.")
        return self


class EventUpdate(BaseModel):
    event_type: Optional[Literal["entry", "exit", "uncertain"]] = None
    review_status: Optional[Literal["confirmed", "needs_review", "rejected"]] = None
    notes: Optional[str] = Field(default=None, max_length=2000)


class LinkExitRequest(BaseModel):
    event_id: str = Field(min_length=36, max_length=36)


class VisitUpdate(BaseModel):
    status: Optional[Literal["inside", "needs_review"]] = None
    operator_note: Optional[str] = Field(default=None, max_length=500)
    identified_by_operator: Optional[bool] = None


class ReconcileRequest(BaseModel):
    # Required when the organization has more than one location.
    location_id: Optional[int] = None
    count: int = Field(ge=0, le=10000)
    reason: str = Field(min_length=3, max_length=500)


class AdjustRequest(BaseModel):
    location_id: Optional[int] = None
    delta: int = Field(ge=-100, le=100)
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("delta")
    @classmethod
    def _nonzero(cls, v: int) -> int:
        if v == 0:
            raise ValueError("Adjustment cannot be zero.")
        return v


class SiteSettingsUpdate(BaseModel):
    site_name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    timezone: Optional[str] = None
    snapshot_retention_days: Optional[int] = Field(default=None, ge=1, le=3650)
    event_retention_days: Optional[int] = Field(default=None, ge=0, le=3650)
    min_confidence: Optional[float] = Field(default=None, ge=0.1, le=0.95)
    cooldown_seconds: Optional[float] = Field(default=None, ge=0, le=60)
    track_timeout_seconds: Optional[float] = Field(default=None, ge=0.5, le=60)
    min_track_hits: Optional[int] = Field(default=None, ge=1, le=60)
    min_side_frames: Optional[int] = Field(default=None, ge=1, le=30)
    line_band: Optional[float] = Field(default=None, ge=0.0, le=0.2)
    anchor_point: Optional[Literal["bottom", "center"]] = None
    snapshot_jpeg_quality: Optional[int] = Field(default=None, ge=40, le=95)
    snapshot_max_width: Optional[int] = Field(default=None, ge=160, le=1920)
    snapshot_storage_limit_mb: Optional[int] = Field(default=None, ge=0, le=1048576)
    alert_retention_days: Optional[int] = Field(default=None, ge=0, le=3650)

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Unknown timezone. Use an IANA name such as Asia/Kolkata.")
        return v


class UserCreate(BaseModel):
    username: str
    password: str = Field(min_length=10, max_length=256)
    role: Literal["admin", "operator", "viewer"] = "operator"
    email: Optional[str] = Field(default=None, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

    @field_validator("username")
    @classmethod
    def _username(cls, v: str) -> str:
        if not USERNAME.match(v):
            raise ValueError("Usernames use 3-64 letters, digits, dots, dashes or underscores.")
        return v


class UserUpdate(BaseModel):
    role: Optional[Literal["admin", "operator", "viewer"]] = None
    email: Optional[str] = Field(default=None, max_length=254, pattern=r"^([^@\s]+@[^@\s]+\.[^@\s]+)?$")
    is_active: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=10, max_length=256)
