"""tenancy, locations, zones, alerts, notifications, anomaly models, reports and sync

Existing single-site data is moved into organization 1 ("Default organization") and
location 1 ("Main location"). Server defaults used for the backfill are removed afterwards,
so application code must always set organization_id explicitly.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

import db

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ORG_SCOPED = ("users", "cameras", "person_tracks", "visits", "detection_events", "occupancy_snapshots", "camera_incidents", "anomaly_events")


def _now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(tzinfo=None)


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("plan", sa.String(32), nullable=False),
        sa.Column("max_cameras", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", db.UTCDateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "locations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("address", sa.String(255), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=True),
        sa.Column("business_hours", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", db.UTCDateTime(timezone=True), nullable=False),
        sa.Column("updated_at", db.UTCDateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "name", name="uq_location_name"),
    )
    op.create_index("ix_locations_organization_id", "locations", ["organization_id"])

    conn = op.get_bind()
    site_name = conn.execute(sa.text("SELECT site_name FROM site_settings ORDER BY id LIMIT 1")).scalar()
    now = _now()
    conn.execute(
        sa.text("INSERT INTO organizations (id, name, slug, plan, is_active, created_at) VALUES (1, :n, 'default', 'standard', :t, :c)"),
        {"n": site_name or "Default organization", "t": True, "c": now},
    )
    conn.execute(
        sa.text("INSERT INTO locations (id, organization_id, name, address, is_active, created_at, updated_at) VALUES (1, 1, 'Main location', '', :t, :c, :c)"),
        {"t": True, "c": now},
    )
    if conn.dialect.name == "postgresql":
        # Explicit ids do not advance PostgreSQL sequences; move them past the seeded rows.
        conn.execute(sa.text("SELECT setval(pg_get_serial_sequence('organizations', 'id'), 1)"))
        conn.execute(sa.text("SELECT setval(pg_get_serial_sequence('locations', 'id'), 1)"))

    # Add tenant columns with a temporary default for the backfill.
    for table in ORG_SCOPED + ("audit_logs", "site_settings"):
        with op.batch_alter_table(table) as b:
            b.add_column(sa.Column("organization_id", sa.Integer(), nullable=table == "audit_logs", server_default="1"))
    with op.batch_alter_table("cameras") as b:
        b.add_column(sa.Column("location_id", sa.Integer(), nullable=False, server_default="1"))
        b.add_column(sa.Column("counting_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
        b.add_column(sa.Column("last_error", sa.Text(), nullable=True))
        b.add_column(sa.Column("last_error_at", db.UTCDateTime(timezone=True), nullable=True))
    with op.batch_alter_table("occupancy_snapshots") as b:
        b.add_column(sa.Column("location_id", sa.Integer(), nullable=False, server_default="1"))
    for table in ("visits", "detection_events"):
        with op.batch_alter_table(table) as b:
            b.add_column(sa.Column("location_id", sa.Integer(), nullable=True))
    conn.execute(sa.text("UPDATE visits SET location_id = 1"))
    conn.execute(sa.text("UPDATE detection_events SET location_id = 1"))
    with op.batch_alter_table("detection_events") as b:
        b.add_column(sa.Column("source_node_id", sa.String(48), nullable=True))
        b.add_column(sa.Column("source_camera_name", sa.String(120), nullable=True))
    with op.batch_alter_table("users") as b:
        b.add_column(sa.Column("email", sa.String(254), nullable=True))
    with op.batch_alter_table("site_settings") as b:
        b.add_column(sa.Column("snapshot_jpeg_quality", sa.Integer(), nullable=False, server_default="85"))
        b.add_column(sa.Column("snapshot_max_width", sa.Integer(), nullable=False, server_default="640"))
        b.add_column(sa.Column("snapshot_storage_limit_mb", sa.Integer(), nullable=False, server_default="2048"))
        b.add_column(sa.Column("alert_retention_days", sa.Integer(), nullable=False, server_default="180"))

    # Remove the backfill defaults and add constraints.
    for table in ORG_SCOPED + ("audit_logs", "site_settings"):
        with op.batch_alter_table(table) as b:
            b.alter_column("organization_id", server_default=None, existing_type=sa.Integer())
            b.create_foreign_key(f"fk_{table}_org", "organizations", ["organization_id"], ["id"], ondelete="CASCADE")
            if table == "site_settings":
                b.create_unique_constraint("uq_site_settings_org", ["organization_id"])
            elif table != "detection_events":
                b.create_index(f"ix_{table}_organization_id", ["organization_id"])
    with op.batch_alter_table("cameras") as b:
        b.alter_column("location_id", server_default=None, existing_type=sa.Integer())
        b.create_foreign_key("fk_cameras_location", "locations", ["location_id"], ["id"], ondelete="RESTRICT")
        b.create_index("ix_cameras_location_id", ["location_id"])
    with op.batch_alter_table("occupancy_snapshots") as b:
        b.alter_column("location_id", server_default=None, existing_type=sa.Integer())
        b.create_foreign_key("fk_occupancy_location", "locations", ["location_id"], ["id"], ondelete="CASCADE")
        b.create_index("ix_occupancy_snapshots_location_id", ["location_id"])
    for table in ("visits", "detection_events"):
        with op.batch_alter_table(table) as b:
            b.create_foreign_key(f"fk_{table}_location", "locations", ["location_id"], ["id"], ondelete="SET NULL")
            b.create_index(f"ix_{table}_location_id", ["location_id"])
    with op.batch_alter_table("detection_events") as b:
        b.create_index("ix_events_org_time", ["organization_id", "occurred_at"])

    op.create_table(
        "camera_zones",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("camera_id", sa.String(48), sa.ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("polygon", sa.Text(), nullable=False),
        sa.Column("dwell_seconds", sa.Float(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", db.UTCDateTime(timezone=True), nullable=False),
        sa.Column("updated_at", db.UTCDateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "alert_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("rule_type", sa.String(40), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("params", sa.Text(), nullable=False),
        sa.Column("cooldown_seconds", sa.Integer(), nullable=False),
        sa.Column("updated_at", db.UTCDateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "rule_type", name="uq_alert_rule_type"),
    )
    op.create_table(
        "alerts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("location_id", sa.Integer(), sa.ForeignKey("locations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("camera_id", sa.String(48), sa.ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True),
        sa.Column("zone_id", sa.Integer(), sa.ForeignKey("camera_zones.id", ondelete="SET NULL"), nullable=True),
        sa.Column("rule_type", sa.String(40), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("metrics", sa.Text(), nullable=False),
        sa.Column("model_score", sa.Float(), nullable=True),
        sa.Column("event_id", sa.String(36), nullable=True, index=True),
        sa.Column("track_label", sa.String(48), nullable=True),
        sa.Column("snapshot_path", sa.String(255), nullable=True),
        sa.Column("snapshot_status", sa.String(24), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("dedup_key", sa.String(200), nullable=False),
        sa.Column("occurrences", sa.Integer(), nullable=False),
        sa.Column("first_seen_at", db.UTCDateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", db.UTCDateTime(timezone=True), nullable=False),
        sa.Column("last_notified_at", db.UTCDateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by", sa.String(64), nullable=True),
        sa.Column("acknowledged_at", db.UTCDateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(64), nullable=True),
        sa.Column("resolved_at", db.UTCDateTime(timezone=True), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("created_at", db.UTCDateTime(timezone=True), nullable=False),
        sa.Column("updated_at", db.UTCDateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_alerts_org_status", "alerts", ["organization_id", "status"])
    op.create_index("ix_alerts_org_time", "alerts", ["organization_id", "last_seen_at"])
    op.create_index("ix_alerts_dedup", "alerts", ["organization_id", "dedup_key"])
    op.create_table(
        "notification_channels",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("min_severity", sa.String(16), nullable=False),
        sa.Column("categories", sa.Text(), nullable=True),
        sa.Column("config_secret", sa.Text(), nullable=False),
        sa.Column("rate_limit_per_hour", sa.Integer(), nullable=False),
        sa.Column("created_at", db.UTCDateTime(timezone=True), nullable=False),
        sa.Column("updated_at", db.UTCDateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("alert_id", sa.String(36), sa.ForeignKey("alerts.id", ondelete="CASCADE"), nullable=True, index=True),
        sa.Column("channel_id", sa.Integer(), sa.ForeignKey("notification_channels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(300), nullable=True),
        sa.Column("next_attempt_at", db.UTCDateTime(timezone=True), nullable=False),
        sa.Column("sent_at", db.UTCDateTime(timezone=True), nullable=True),
        sa.Column("created_at", db.UTCDateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_delivery_status", "notification_deliveries", ["status", "next_attempt_at"])
    op.create_table(
        "anomaly_models",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("version", sa.String(40), nullable=False),
        sa.Column("algorithm", sa.String(40), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("feature_schema_version", sa.Integer(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("n_samples", sa.Integer(), nullable=False),
        sa.Column("artifact_path", sa.String(255), nullable=True),
        sa.Column("artifact_sha256", sa.String(64), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("trained_by", sa.String(64), nullable=True),
        sa.Column("trained_at", db.UTCDateTime(timezone=True), nullable=False),
        sa.Column("last_inference_at", db.UTCDateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "report_schedules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("frequency", sa.String(16), nullable=False),
        sa.Column("location_id", sa.Integer(), sa.ForeignKey("locations.id", ondelete="CASCADE"), nullable=True),
        sa.Column("channel_id", sa.Integer(), sa.ForeignKey("notification_channels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_period_end", sa.String(10), nullable=True),
        sa.Column("last_run_at", db.UTCDateTime(timezone=True), nullable=True),
        sa.Column("created_at", db.UTCDateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "sync_outbox",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_type", sa.String(24), nullable=False),
        sa.Column("entity_id", sa.String(64), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(300), nullable=True),
        sa.Column("next_attempt_at", db.UTCDateTime(timezone=True), nullable=False),
        sa.Column("created_at", db.UTCDateTime(timezone=True), nullable=False),
        sa.Column("sent_at", db.UTCDateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_outbox_status", "sync_outbox", ["status", "next_attempt_at"])
    op.create_table(
        "sync_nodes",
        sa.Column("id", sa.String(48), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("location_id", sa.Integer(), sa.ForeignKey("locations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_seen_at", db.UTCDateTime(timezone=True), nullable=True),
        sa.Column("last_batch_size", sa.Integer(), nullable=False),
        sa.Column("created_at", db.UTCDateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    for table in ("sync_nodes", "sync_outbox", "report_schedules", "anomaly_models", "notification_deliveries",
                  "notification_channels", "alerts", "alert_rules", "camera_zones"):
        op.drop_table(table)
    with op.batch_alter_table("detection_events") as b:
        b.drop_index("ix_events_org_time")
        b.drop_column("source_camera_name")
        b.drop_column("source_node_id")
    for table in ("visits", "detection_events"):
        with op.batch_alter_table(table) as b:
            b.drop_index(f"ix_{table}_location_id")
            b.drop_constraint(f"fk_{table}_location", type_="foreignkey")
            b.drop_column("location_id")
    with op.batch_alter_table("occupancy_snapshots") as b:
        b.drop_index("ix_occupancy_snapshots_location_id")
        b.drop_constraint("fk_occupancy_location", type_="foreignkey")
        b.drop_column("location_id")
    with op.batch_alter_table("cameras") as b:
        b.drop_index("ix_cameras_location_id")
        b.drop_constraint("fk_cameras_location", type_="foreignkey")
        for col in ("location_id", "counting_enabled", "last_error", "last_error_at"):
            b.drop_column(col)
    with op.batch_alter_table("site_settings") as b:
        for col in ("snapshot_jpeg_quality", "snapshot_max_width", "snapshot_storage_limit_mb", "alert_retention_days"):
            b.drop_column(col)
    with op.batch_alter_table("users") as b:
        b.drop_column("email")
    for table in ORG_SCOPED + ("audit_logs", "site_settings"):
        with op.batch_alter_table(table) as b:
            if table == "site_settings":
                b.drop_constraint("uq_site_settings_org", type_="unique")
            elif table != "detection_events":
                b.drop_index(f"ix_{table}_organization_id")
            b.drop_constraint(f"fk_{table}_org", type_="foreignkey")
            b.drop_column("organization_id")
    op.drop_index("ix_locations_organization_id", "locations")
    op.drop_table("locations")
    op.drop_table("organizations")
