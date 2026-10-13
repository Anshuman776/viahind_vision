"""Request validation schemas for the surveillance API."""

import re
from typing import Literal, Optional
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
    count: int = Field(ge=0, le=10000)
    reason: str = Field(min_length=3, max_length=500)


class AdjustRequest(BaseModel):
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
    role: Literal["admin", "operator"] = "operator"

    @field_validator("username")
    @classmethod
    def _username(cls, v: str) -> str:
        if not USERNAME.match(v):
            raise ValueError("Usernames use 3-64 letters, digits, dots, dashes or underscores.")
        return v


class UserUpdate(BaseModel):
    role: Optional[Literal["admin", "operator"]] = None
    is_active: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=10, max_length=256)
