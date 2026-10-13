"""
VIAHIND Vision - Persistent surveillance entities (SQLAlchemy ORM).

The schema is managed by Alembic migrations in backend/migrations. Any change here
must be accompanied by a new migration revision.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base, UTCDateTime, utcnow

# Enumerated values are stored as short strings and validated at the API boundary.
ROLES = ("admin", "operator")
SOURCE_TYPES = ("browser", "device", "network", "file")
EVENT_TYPES = ("entry", "exit", "uncertain")
REVIEW_STATUSES = ("auto", "needs_review", "confirmed", "corrected", "rejected")
MATCH_STATUSES = ("not_applicable", "matched", "unmatched")
SNAPSHOT_STATUSES = ("saved", "none", "failed", "skipped_low_storage", "purged")
VISIT_STATUSES = ("inside", "exited", "needs_review", "voided")
VISIT_MATCH_METHODS = ("tracker", "manual")
OCCUPANCY_KINDS = ("reconcile", "adjust")
INCIDENT_KINDS = ("disconnected", "error", "service_restart")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="operator")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)


class SiteSettings(Base):
    """Single-row table holding operational settings for the configured PG site."""

    __tablename__ = "site_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    site_name: Mapped[str] = mapped_column(String(120), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    # 0 keeps event records indefinitely.
    event_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    min_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.45)
    cooldown_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=3.0)
    track_timeout_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=4.0)
    min_track_hits: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    min_side_frames: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    # Hysteresis band around the entrance line, as a fraction of min(frame width, height).
    line_band: Mapped[float] = mapped_column(Float, nullable=False, default=0.03)
    anchor_point: Mapped[str] = mapped_column(String(16), nullable=False, default="bottom")
    next_person_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    location: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    # Encrypted source (URL, device index, env reference or file name). Never returned by the API.
    source_secret: Mapped[Optional[str]] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Whether an operator left the camera running; used to resume after a restart.
    desired_running: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    detection_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Entrance line in normalised frame coordinates (0..1). Null until configured.
    line_x1: Mapped[Optional[float]] = mapped_column(Float)
    line_y1: Mapped[Optional[float]] = mapped_column(Float)
    line_x2: Mapped[Optional[float]] = mapped_column(Float)
    line_y2: Mapped[Optional[float]] = mapped_column(Float)
    # +1: entering means moving toward the left-hand normal of (x1,y1)->(x2,y2); -1 the opposite.
    entry_side: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)

    @property
    def has_line(self) -> bool:
        return None not in (self.line_x1, self.line_y1, self.line_x2, self.line_y2)


class PersonTrack(Base):
    """A tracker track (camera session + tracker ID) that produced at least one event.

    Track IDs are only unique within one camera worker session; they say nothing about
    a person's identity.
    """

    __tablename__ = "person_tracks"
    __table_args__ = (UniqueConstraint("camera_id", "session_id", "tracker_id", name="uq_track_session"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[str] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[str] = mapped_column(String(36), nullable=False)
    tracker_id: Mapped[int] = mapped_column(Integer, nullable=False)
    person_label: Mapped[str] = mapped_column(String(48), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)


class Visit(Base):
    __tablename__ = "visits"
    __table_args__ = (
        Index("ix_visits_status", "status"),
        Index("ix_visits_entry_at", "entry_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    person_label: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    # Event references are plain indexed columns (no FK) to avoid a visits <-> events cycle;
    # integrity is maintained by services/events.py, the only writer.
    entry_event_id: Mapped[Optional[str]] = mapped_column(String(36), index=True)
    exit_event_id: Mapped[Optional[str]] = mapped_column(String(36), index=True)
    entry_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)
    exit_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)
    entry_camera_id: Mapped[Optional[str]] = mapped_column(ForeignKey("cameras.id", ondelete="SET NULL"))
    exit_camera_id: Mapped[Optional[str]] = mapped_column(ForeignKey("cameras.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="inside")
    match_method: Mapped[Optional[str]] = mapped_column(String(16))
    # Optional operator-entered note, e.g. "Resident, room 12". Labels stay pseudonymous otherwise.
    operator_note: Mapped[Optional[str]] = mapped_column(Text)
    identified_by_operator: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class DetectionEvent(Base):
    __tablename__ = "detection_events"
    __table_args__ = (
        Index("ix_events_occurred_at", "occurred_at"),
        Index("ix_events_camera_time", "camera_id", "occurred_at"),
        Index("ix_events_type", "event_type"),
        Index("ix_events_review", "review_status"),
        Index("ix_events_label", "person_label"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    camera_id: Mapped[Optional[str]] = mapped_column(ForeignKey("cameras.id", ondelete="SET NULL"))
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    # What the system originally recorded, kept when an operator corrects the type.
    original_event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    person_label: Mapped[str] = mapped_column(String(48), nullable=False)
    track_id: Mapped[Optional[int]] = mapped_column(ForeignKey("person_tracks.id", ondelete="SET NULL"))
    visit_id: Mapped[Optional[int]] = mapped_column(ForeignKey("visits.id", ondelete="SET NULL"))
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    snapshot_path: Mapped[Optional[str]] = mapped_column(String(255))
    snapshot_status: Mapped[str] = mapped_column(String(24), nullable=False, default="none")
    review_status: Mapped[str] = mapped_column(String(16), nullable=False, default="auto")
    match_status: Mapped[str] = mapped_column(String(16), nullable=False, default="not_applicable")
    uncertain_reason: Mapped[Optional[str]] = mapped_column(String(64))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)

    camera = relationship("Camera", lazy="joined")


class OccupancySnapshot(Base):
    """Operator reconciliation ("there are N people inside now") or manual +/- adjustment."""

    __tablename__ = "occupancy_snapshots"
    __table_args__ = (Index("ix_occupancy_recorded_at", "recorded_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    value: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class CameraIncident(Base):
    """A period where events may have been missed (disconnection, error, service restart)."""

    __tablename__ = "camera_incidents"
    __table_args__ = (Index("ix_incidents_started_at", "started_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[Optional[str]] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    ended_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_entity", "entity_type", "entity_id"),
        Index("ix_audit_occurred_at", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=False, default="{}")


class AnomalyEvent(Base):
    """Output of the existing anomaly (fight) classifier, recorded through vision/anomaly.py."""

    __tablename__ = "anomaly_events"
    __table_args__ = (Index("ix_anomaly_occurred_at", "occurred_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[Optional[str]] = mapped_column(ForeignKey("cameras.id", ondelete="SET NULL"))
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    model_name: Mapped[str] = mapped_column(String(120), nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_output: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    review_status: Mapped[str] = mapped_column(String(16), nullable=False, default="needs_review")
