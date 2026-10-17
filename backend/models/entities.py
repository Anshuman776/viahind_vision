"""
VIAHIND Vision - Persistent entities (SQLAlchemy ORM).

Every business record belongs to exactly one organization (tenant). API handlers scope every
query by the signed-in user's organization (see services/tenancy.py).

The schema is managed by Alembic migrations in backend/migrations. Any change here
must be accompanied by a new migration revision.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base, UTCDateTime, utcnow

# Enumerated values are stored as short strings and validated at the API boundary.
# admin: configuration, users, evidence deletion. operator: monitoring, review, reconciliation.
# viewer: dashboards and reports only (no snapshots, no camera control, no review).
ROLES = ("admin", "operator", "viewer")
SOURCE_TYPES = ("browser", "device", "network", "file")
EVENT_TYPES = ("entry", "exit", "uncertain")
REVIEW_STATUSES = ("auto", "needs_review", "confirmed", "corrected", "rejected")
MATCH_STATUSES = ("not_applicable", "matched", "unmatched")
SNAPSHOT_STATUSES = ("saved", "none", "failed", "skipped_low_storage", "skipped_storage_limit", "purged", "deleted")
VISIT_STATUSES = ("inside", "exited", "needs_review", "voided")
VISIT_MATCH_METHODS = ("tracker", "manual")
OCCUPANCY_KINDS = ("reconcile", "adjust")
INCIDENT_KINDS = ("disconnected", "error", "service_restart")
ZONE_KINDS = ("restricted", "monitored")
ALERT_SEVERITIES = ("info", "low", "medium", "high", "critical")
ALERT_STATUSES = ("new", "acknowledged", "resolved", "dismissed")
OPEN_ALERT_STATUSES = ("new", "acknowledged")
CHANNEL_KINDS = ("email", "webhook", "telegram")
DELIVERY_STATUSES = ("pending", "sent", "failed", "suppressed")


def _org_fk(nullable: bool = False, index: bool = True):
    return mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=nullable, index=index)


class Organization(Base):
    """A tenant. Every business record belongs to exactly one organization."""

    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    # Billing integration points: the plan name and its limits are enforced by the API.
    plan: Mapped[str] = mapped_column(String(32), nullable=False, default="standard")
    max_cameras: Mapped[Optional[int]] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class Location(Base):
    """A business premises (shop, restaurant, hotel, office) with its own cameras and occupancy."""

    __tablename__ = "locations"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_location_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = _org_fk()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    address: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # Maximum expected occupancy; used by the occupancy alert rule. Null = not configured.
    capacity: Mapped[Optional[int]] = mapped_column(Integer)
    # JSON {"mon": [["09:00", "21:00"]], ...} in the organization timezone. Null = not configured.
    business_hours: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = _org_fk()
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(254))
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="operator")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)


class SiteSettings(Base):
    """Operational settings of one organization (one row per organization)."""

    __tablename__ = "site_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, unique=True)
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
    # Event evidence
    snapshot_jpeg_quality: Mapped[int] = mapped_column(Integer, nullable=False, default=85)
    snapshot_max_width: Mapped[int] = mapped_column(Integer, nullable=False, default=640)
    # 0 = no limit beyond MIN_FREE_DISK_MB.
    snapshot_storage_limit_mb: Mapped[int] = mapped_column(Integer, nullable=False, default=2048)
    # Closed alerts older than this are deleted (0 keeps them).
    alert_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=180)
    # Outgoing mail server (SMTP) set from the console, encrypted. Null falls back to the SMTP_* settings.
    mail_config_secret: Mapped[Optional[str]] = mapped_column(Text)
    # Head guard policy as JSON (see services/head_guard.py). Null uses the defaults.
    head_guard_config: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    organization_id: Mapped[int] = _org_fk()
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id", ondelete="RESTRICT"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # Free-text position within the premises, e.g. "Front door, facing street".
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
    # Whether this camera's line contributes to footfall/occupancy (one counting camera per doorway).
    counting_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Guard assignment (services/guards.py): the post this camera watches and the duties it performs.
    # A null post means "general watch"; null duties mean the post's default duties.
    guard_name: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    guard_post: Mapped[Optional[str]] = mapped_column(String(24))
    guard_duties: Mapped[Optional[str]] = mapped_column(Text)
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    last_error_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)

    @property
    def has_line(self) -> bool:
        return None not in (self.line_x1, self.line_y1, self.line_x2, self.line_y2)


class CameraZone(Base):
    """A polygon on a camera image (normalised coordinates) watched by the zone rules."""

    __tablename__ = "camera_zones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = _org_fk()
    camera_id: Mapped[str] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    # restricted: any presence raises an alert. monitored: only dwell beyond dwell_seconds does.
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="monitored")
    # JSON [[x, y], ...] with 3-32 points in 0..1.
    polygon: Mapped[str] = mapped_column(Text, nullable=False)
    dwell_seconds: Mapped[Optional[float]] = mapped_column(Float)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class PersonTrack(Base):
    """A tracker track (camera session + tracker ID) that produced at least one event.

    Track IDs are only unique within one camera worker session; they say nothing about
    a person's identity.
    """

    __tablename__ = "person_tracks"
    __table_args__ = (UniqueConstraint("camera_id", "session_id", "tracker_id", name="uq_track_session"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = _org_fk()
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
    organization_id: Mapped[int] = _org_fk()
    location_id: Mapped[Optional[int]] = mapped_column(ForeignKey("locations.id", ondelete="SET NULL"), index=True)
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
    # Optional operator-entered note. Labels stay pseudonymous otherwise.
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
        Index("ix_events_org_time", "organization_id", "occurred_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[int] = _org_fk(index=False)
    location_id: Mapped[Optional[int]] = mapped_column(ForeignKey("locations.id", ondelete="SET NULL"), index=True)
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
    # Set on a cloud instance for events received from an edge node (camera_id is then null).
    source_node_id: Mapped[Optional[str]] = mapped_column(String(48))
    source_camera_name: Mapped[Optional[str]] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)

    camera = relationship("Camera", lazy="joined")


class OccupancySnapshot(Base):
    """Operator reconciliation ("there are N people inside now") or manual +/- adjustment."""

    __tablename__ = "occupancy_snapshots"
    __table_args__ = (Index("ix_occupancy_recorded_at", "recorded_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = _org_fk()
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id", ondelete="CASCADE"), nullable=False, index=True)
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
    organization_id: Mapped[int] = _org_fk()
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
    # Null only for platform-level entries (e.g. creating an organization from the CLI).
    organization_id: Mapped[Optional[int]] = _org_fk(nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=False, default="{}")


class AnomalyEvent(Base):
    """Output of the existing video anomaly (fight) classifier, recorded through vision/anomaly.py."""

    __tablename__ = "anomaly_events"
    __table_args__ = (Index("ix_anomaly_occurred_at", "occurred_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = _org_fk()
    camera_id: Mapped[Optional[str]] = mapped_column(ForeignKey("cameras.id", ondelete="SET NULL"))
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    model_name: Mapped[str] = mapped_column(String(120), nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_output: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    review_status: Mapped[str] = mapped_column(String(16), nullable=False, default="needs_review")


class AlertRule(Base):
    """Organization-level configuration of one alert rule type (see services/alert_rules.py)."""

    __tablename__ = "alert_rules"
    __table_args__ = (UniqueConstraint("organization_id", "rule_type", name="uq_alert_rule_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = _org_fk()
    rule_type: Mapped[str] = mapped_column(String(40), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    # JSON object of rule parameters, validated against the rule's schema.
    params: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    # Minimum time between notifications for the same ongoing condition.
    cooldown_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=900)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class Alert(Base):
    """A reviewable alert with an explainable reason. Alerts never establish misconduct on their own."""

    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alerts_org_status", "organization_id", "status"),
        Index("ix_alerts_org_time", "organization_id", "last_seen_at"),
        Index("ix_alerts_dedup", "organization_id", "dedup_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[int] = _org_fk(index=False)
    location_id: Mapped[Optional[int]] = mapped_column(ForeignKey("locations.id", ondelete="SET NULL"))
    camera_id: Mapped[Optional[str]] = mapped_column(ForeignKey("cameras.id", ondelete="SET NULL"))
    zone_id: Mapped[Optional[int]] = mapped_column(ForeignKey("camera_zones.id", ondelete="SET NULL"))
    rule_type: Mapped[str] = mapped_column(String(40), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    metrics: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    model_score: Mapped[Optional[float]] = mapped_column(Float)
    event_id: Mapped[Optional[str]] = mapped_column(String(36), index=True)
    track_label: Mapped[Optional[str]] = mapped_column(String(48))
    snapshot_path: Mapped[Optional[str]] = mapped_column(String(255))
    snapshot_status: Mapped[str] = mapped_column(String(24), nullable=False, default="none")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="new")
    dedup_key: Mapped[str] = mapped_column(String(200), nullable=False)
    occurrences: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    last_notified_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)
    acknowledged_by: Mapped[Optional[str]] = mapped_column(String(64))
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)
    resolved_by: Mapped[Optional[str]] = mapped_column(String(64))
    resolved_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)
    resolution_note: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class NotificationChannel(Base):
    __tablename__ = "notification_channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = _org_fk()
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    min_severity: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    # JSON list of categories; null = all categories.
    categories: Mapped[Optional[str]] = mapped_column(Text)
    # Encrypted JSON: {"recipients": [...]} for email, {"url": ..., "secret": ...} for webhooks.
    config_secret: Mapped[str] = mapped_column(Text, nullable=False)
    rate_limit_per_hour: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"
    __table_args__ = (Index("ix_delivery_status", "status", "next_attempt_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = _org_fk()
    alert_id: Mapped[Optional[str]] = mapped_column(ForeignKey("alerts.id", ondelete="CASCADE"), index=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("notification_channels.id", ondelete="CASCADE"), nullable=False)
    # "alert", "report" or "test"
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="alert")
    subject: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    payload: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[Optional[str]] = mapped_column(String(300))
    next_attempt_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    sent_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class AnomalyModel(Base):
    """Registry of trained event-level anomaly models (artifacts live in MODEL_DIR)."""

    __tablename__ = "anomaly_models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = _org_fk()
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    algorithm: Mapped[str] = mapped_column(String(40), nullable=False)
    # ready | insufficient_data | failed | retired
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    feature_schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    # JSON: feature names, training means/stds, threshold, training window, data quality.
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    n_samples: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    artifact_path: Mapped[Optional[str]] = mapped_column(String(255))
    artifact_sha256: Mapped[Optional[str]] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    trained_by: Mapped[Optional[str]] = mapped_column(String(64))
    trained_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    last_inference_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)


class ReportSchedule(Base):
    __tablename__ = "report_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = _org_fk()
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    frequency: Mapped[str] = mapped_column(String(16), nullable=False)  # daily | weekly | monthly
    location_id: Mapped[Optional[int]] = mapped_column(ForeignKey("locations.id", ondelete="CASCADE"))
    channel_id: Mapped[int] = mapped_column(ForeignKey("notification_channels.id", ondelete="CASCADE"), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_period_end: Mapped[Optional[str]] = mapped_column(String(10))  # YYYY-MM-DD of the last period sent
    last_run_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class SyncOutbox(Base):
    """Edge side: event payloads waiting to be pushed to the cloud (no images, no credentials)."""

    __tablename__ = "sync_outbox"
    __table_args__ = (Index("ix_outbox_status", "status", "next_attempt_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = _org_fk(index=False)
    entity_type: Mapped[str] = mapped_column(String(24), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[Optional[str]] = mapped_column(String(300))
    next_attempt_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    sent_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)


class SyncNode(Base):
    """Cloud side: an edge node allowed to push events into one location of an organization."""

    __tablename__ = "sync_nodes"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    organization_id: Mapped[int] = _org_fk()
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # SHA-256 of the node token; the token itself is shown once at creation.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)
    last_batch_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


GUARD_INCIDENT_STATUSES = ("open", "acknowledged", "resolved")


class GuardIncident(Base):
    """A situation tracked by the head guard: one or more related guard reports (alerts) that
    happened close together at one location. Incidents are for human follow-up, not proof."""

    __tablename__ = "guard_incidents"
    __table_args__ = (Index("ix_guard_incidents_org_status", "organization_id", "status", "last_seen_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[int] = _org_fk(index=False)
    location_id: Mapped[Optional[int]] = mapped_column(ForeignKey("locations.id", ondelete="SET NULL"))
    # security: reports about people (fights, restricted areas, curfew...). system: cameras that cannot see.
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="security")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # JSON lists
    actions: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    camera_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    alert_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    report_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    escalated_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)
    escalated_severity: Mapped[Optional[str]] = mapped_column(String(16))
    acknowledged_by: Mapped[Optional[str]] = mapped_column(String(64))
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)
    resolved_by: Mapped[Optional[str]] = mapped_column(String(64))
    resolved_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)
    resolution_note: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
