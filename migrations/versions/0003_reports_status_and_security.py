"""add investigation reports, alert status history, token revocation and login throttling

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-23

This migration is additive: no existing table, column or constraint is altered,
so reports, alerts and audit data created by 0001/0002 stay valid.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "investigation_reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("alert_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("generator", sa.String(length=32), nullable=False),
        sa.Column("generator_version", sa.String(length=32), nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("evidence_count", sa.Integer(), nullable=False),
        sa.Column(
            "evidence_truncated",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_username", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finalized_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("finalized_by_username", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "status IN ('draft', 'finalized', 'superseded')",
            name="ck_investigation_reports_status",
        ),
        sa.CheckConstraint(
            "generator IN ('deterministic', 'agent')",
            name="ck_investigation_reports_generator",
        ),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_investigation_reports_version",
        ),
        sa.CheckConstraint(
            "status <> 'finalized' OR finalized_at IS NOT NULL",
            name="ck_investigation_reports_finalized_at",
        ),
        sa.ForeignKeyConstraint(
            ["alert_id"],
            ["alerts.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["finalized_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "alert_id",
            "version",
            name="uq_investigation_reports_alert_version",
        ),
    )
    op.create_index(
        "ix_investigation_reports_alert_version",
        "investigation_reports",
        ["alert_id", "version"],
    )
    op.create_index(
        "ix_investigation_reports_status",
        "investigation_reports",
        ["status"],
    )

    op.create_table(
        "alert_status_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("alert_id", sa.Uuid(), nullable=False),
        sa.Column("from_status", sa.String(length=20), nullable=True),
        sa.Column("to_status", sa.String(length=20), nullable=False),
        sa.Column("changed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("changed_by_username", sa.String(length=64), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "to_status IN ('open', 'acknowledged', 'investigating', 'closed')",
            name="ck_alert_status_history_to_status",
        ),
        sa.CheckConstraint(
            "from_status IS NULL OR from_status IN "
            "('open', 'acknowledged', 'investigating', 'closed')",
            name="ck_alert_status_history_from_status",
        ),
        sa.ForeignKeyConstraint(
            ["alert_id"],
            ["alerts.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["changed_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_alert_status_history_alert_created",
        "alert_status_history",
        ["alert_id", "created_at"],
    )

    op.create_table(
        "revoked_tokens",
        sa.Column("jti", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("jti"),
    )
    op.create_index(
        "ix_revoked_tokens_expires_at",
        "revoked_tokens",
        ["expires_at"],
    )
    op.create_index(
        "ix_revoked_tokens_user_id",
        "revoked_tokens",
        ["user_id"],
    )

    op.create_table(
        "login_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("subject_hash", sa.String(length=64), nullable=False),
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
        sa.Column("succeeded", sa.Boolean(), nullable=False),
        sa.Column(
            "attempted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_login_attempts_subject_attempted",
        "login_attempts",
        ["subject_hash", "attempted_at"],
    )
    op.create_index(
        "ix_login_attempts_ip_attempted",
        "login_attempts",
        ["ip_hash", "attempted_at"],
    )
    op.create_index(
        "ix_login_attempts_attempted_at",
        "login_attempts",
        ["attempted_at"],
    )


def downgrade() -> None:
    op.drop_table("login_attempts")
    op.drop_table("revoked_tokens")
    op.drop_table("alert_status_history")
    op.drop_table("investigation_reports")
