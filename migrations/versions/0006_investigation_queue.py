"""add a durable investigation queue

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-24

Turns ``investigations`` into a small durable queue: a task is stored as
``pending``, claimed by a worker with a lease, and only then becomes ``running``.
An expired lease means the worker died, so the row is claimable again.

The status CHECK constraint has to change to allow ``pending``. PostgreSQL can
alter it in place; SQLite cannot, so it goes through batch mode there.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUSES_OLD = "'running', 'succeeded', 'failed', 'limit_reached'"
_STATUSES_NEW = "'pending', 'running', 'succeeded', 'failed', 'limit_reached'"


def upgrade() -> None:
    op.add_column(
        "investigations",
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "investigations",
        sa.Column("max_attempts", sa.Integer(), server_default="2", nullable=False),
    )
    op.add_column(
        "investigations",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "investigations",
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "investigations",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "investigations",
        sa.Column("error_code", sa.String(length=32), nullable=True),
    )
    op.create_index(
        "ix_investigations_queue",
        "investigations",
        ["status", "next_attempt_at"],
    )

    # A retried task re-runs from round 1, so the trace must be scoped by
    # attempt. Without this, the second attempt collides on (id, round_index).
    op.add_column(
        "investigation_rounds",
        sa.Column("attempt_index", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column(
        "investigation_tool_calls",
        sa.Column("attempt_index", sa.Integer(), server_default="1", nullable=False),
    )
    op.drop_index(
        "ix_investigation_rounds_investigation",
        table_name="investigation_rounds",
    )
    op.create_index(
        "ix_investigation_rounds_investigation",
        "investigation_rounds",
        ["investigation_id", "attempt_index", "round_index"],
    )

    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("investigations") as batch:
            batch.drop_constraint("ck_investigations_status", type_="check")
            batch.create_check_constraint(
                "ck_investigations_status",
                f"status IN ({_STATUSES_NEW})",
            )
        with op.batch_alter_table("investigation_rounds") as batch:
            batch.drop_constraint("uq_investigation_rounds_index", type_="unique")
            batch.create_unique_constraint(
                "uq_investigation_rounds_attempt_index",
                ["investigation_id", "attempt_index", "round_index"],
            )
    else:
        op.drop_constraint(
            "ck_investigations_status", "investigations", type_="check"
        )
        op.create_check_constraint(
            "ck_investigations_status",
            "investigations",
            f"status IN ({_STATUSES_NEW})",
        )
        op.drop_constraint(
            "uq_investigation_rounds_index",
            "investigation_rounds",
            type_="unique",
        )
        op.create_unique_constraint(
            "uq_investigation_rounds_attempt_index",
            "investigation_rounds",
            ["investigation_id", "attempt_index", "round_index"],
        )


def downgrade() -> None:
    # Anything still pending/running would violate the old constraint.
    op.execute(
        "UPDATE investigations SET status = 'failed' "
        "WHERE status IN ('pending', 'running')"
    )

    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("investigations") as batch:
            batch.drop_constraint("ck_investigations_status", type_="check")
            batch.create_check_constraint(
                "ck_investigations_status",
                f"status IN ({_STATUSES_OLD})",
            )
        with op.batch_alter_table("investigation_rounds") as batch:
            batch.drop_constraint(
                "uq_investigation_rounds_attempt_index", type_="unique"
            )
            batch.create_unique_constraint(
                "uq_investigation_rounds_index",
                ["investigation_id", "round_index"],
            )
    else:
        op.drop_constraint(
            "ck_investigations_status", "investigations", type_="check"
        )
        op.create_check_constraint(
            "ck_investigations_status",
            "investigations",
            f"status IN ({_STATUSES_OLD})",
        )
        op.drop_constraint(
            "uq_investigation_rounds_attempt_index",
            "investigation_rounds",
            type_="unique",
        )
        op.create_unique_constraint(
            "uq_investigation_rounds_index",
            "investigation_rounds",
            ["investigation_id", "round_index"],
        )

    # The index still references attempt_index, so it goes before the column.
    op.drop_index(
        "ix_investigation_rounds_investigation",
        table_name="investigation_rounds",
    )
    op.create_index(
        "ix_investigation_rounds_investigation",
        "investigation_rounds",
        ["investigation_id", "round_index"],
    )

    op.drop_index("ix_investigations_queue", table_name="investigations")
    op.drop_column("investigation_tool_calls", "attempt_index")
    op.drop_column("investigation_rounds", "attempt_index")
    for column in (
        "error_code",
        "started_at",
        "next_attempt_at",
        "lease_expires_at",
        "max_attempts",
        "attempt_count",
    ):
        op.drop_column("investigations", column)
