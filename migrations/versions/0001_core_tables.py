"""create core security event and alert tables

Revision ID: 0001
Revises:
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "security_events",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("source_ip", sa.String(length=45), nullable=True),
        sa.Column("asset_id", sa.String(length=255), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("raw_message", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "outcome IN ('success', 'failure', 'unknown')",
            name="ck_security_events_outcome",
        ),
        sa.CheckConstraint(
            "length(raw_message) <= 8192",
            name="ck_security_events_raw_message_length",
        ),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index(
        "ix_security_events_occurred_at",
        "security_events",
        ["occurred_at"],
    )
    op.create_index(
        "ix_security_events_type_outcome_occurred_at",
        "security_events",
        ["event_type", "outcome", "occurred_at"],
    )
    op.create_index(
        "ix_security_events_user_ip_occurred_at",
        "security_events",
        ["username", "source_ip", "occurred_at"],
    )
    op.create_index(
        "ix_security_events_source",
        "security_events",
        ["source"],
    )

    op.create_table(
        "alerts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.String(length=64), nullable=False),
        sa.Column("rule_version", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("dedup_key", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "severity IN ('info', 'low', 'medium', 'high', 'critical')",
            name="ck_alerts_severity",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'acknowledged', 'investigating', 'closed')",
            name="ck_alerts_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedup_key", name="uq_alerts_dedup_key"),
    )
    op.create_index(
        "ix_alerts_status_created_at",
        "alerts",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_alerts_severity_created_at",
        "alerts",
        ["severity", "created_at"],
    )

    op.create_table(
        "alert_events",
        sa.Column("alert_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column(
            "linked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["alert_id"],
            ["alerts.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["security_events.event_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("alert_id", "event_id"),
    )
    op.create_index(
        "ix_alert_events_event_id",
        "alert_events",
        ["event_id"],
    )


def downgrade() -> None:
    op.drop_table("alert_events")
    op.drop_table("alerts")
    op.drop_table("security_events")
