"""guard posts and duties per camera, head guard incidents, console-managed mail server

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

import db

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("cameras") as b:
        b.add_column(sa.Column("guard_name", sa.String(60), nullable=False, server_default=""))
        b.add_column(sa.Column("guard_post", sa.String(24), nullable=True))
        b.add_column(sa.Column("guard_duties", sa.Text(), nullable=True))
    with op.batch_alter_table("site_settings") as b:
        b.add_column(sa.Column("mail_config_secret", sa.Text(), nullable=True))
        b.add_column(sa.Column("head_guard_config", sa.Text(), nullable=True))

    op.create_table(
        "guard_incidents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("location_id", sa.Integer(), sa.ForeignKey("locations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("actions", sa.Text(), nullable=False),
        sa.Column("camera_ids", sa.Text(), nullable=False),
        sa.Column("alert_ids", sa.Text(), nullable=False),
        sa.Column("report_count", sa.Integer(), nullable=False),
        sa.Column("first_seen_at", db.UTCDateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", db.UTCDateTime(timezone=True), nullable=False),
        sa.Column("escalated_at", db.UTCDateTime(timezone=True), nullable=True),
        sa.Column("escalated_severity", sa.String(16), nullable=True),
        sa.Column("acknowledged_by", sa.String(64), nullable=True),
        sa.Column("acknowledged_at", db.UTCDateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(64), nullable=True),
        sa.Column("resolved_at", db.UTCDateTime(timezone=True), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("created_at", db.UTCDateTime(timezone=True), nullable=False),
        sa.Column("updated_at", db.UTCDateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_guard_incidents_org_status", "guard_incidents", ["organization_id", "status", "last_seen_at"])


def downgrade() -> None:
    op.drop_index("ix_guard_incidents_org_status", table_name="guard_incidents")
    op.drop_table("guard_incidents")
    with op.batch_alter_table("site_settings") as b:
        b.drop_column("head_guard_config")
        b.drop_column("mail_config_secret")
    with op.batch_alter_table("cameras") as b:
        b.drop_column("guard_duties")
        b.drop_column("guard_post")
        b.drop_column("guard_name")
