"""add investigation round tracing and request correlation

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-24

Additive migration: creates one new table and adds two nullable columns. No
existing column, constraint or index is altered, so a downgrade is a pure drop.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "investigations",
        sa.Column("request_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "investigations",
        sa.Column("duration_ms", sa.Integer(), nullable=True),
    )

    op.create_table(
        "investigation_rounds",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("investigation_id", sa.Uuid(), nullable=False),
        sa.Column("round_index", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("tool_call_count", sa.Integer(), nullable=False),
        sa.Column("error", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "outcome IN ('tool_calls', 'findings', 'error', 'budget_exhausted')",
            name="ck_investigation_rounds_outcome",
        ),
        sa.CheckConstraint(
            "round_index >= 1",
            name="ck_investigation_rounds_index",
        ),
        sa.ForeignKeyConstraint(
            ["investigation_id"],
            ["investigations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "investigation_id",
            "round_index",
            name="uq_investigation_rounds_index",
        ),
    )
    op.create_index(
        "ix_investigation_rounds_investigation",
        "investigation_rounds",
        ["investigation_id", "round_index"],
    )


def downgrade() -> None:
    op.drop_table("investigation_rounds")
    op.drop_column("investigations", "duration_ms")
    op.drop_column("investigations", "request_id")
