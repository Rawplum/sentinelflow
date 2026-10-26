"""Agent investigation task and tool-call records."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from sentinelflow.core.time import utcnow
from sentinelflow.db.session import Base

#: pending -> running -> succeeded | failed | limit_reached
#: A running task whose lease expires goes back to pending (retry) or failed.
INVESTIGATION_STATUSES = ("pending", "running", "succeeded", "failed", "limit_reached")
TOOL_CALL_STATUSES = ("ok", "error", "timeout", "denied", "invalid")
#: How a single model round ended. Recorded for observability only.
ROUND_OUTCOMES = ("tool_calls", "findings", "error", "budget_exhausted")


class Investigation(Base):
    """One bounded agent investigation of a single alert."""

    __tablename__ = "investigations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', 'limit_reached')",
            name="ck_investigations_status",
        ),
        Index("ix_investigations_alert_created", "alert_id", "created_at"),
        Index("ix_investigations_status", "status"),
        Index("ix_investigations_queue", "status", "next_attempt_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    alert_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("alerts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )
    model_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    rounds_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tool_calls_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    #: Correlation id of the HTTP request that created the investigation.
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: End-to-end wall clock time of the run, filled in when it terminates.
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- durable queue bookkeeping ---------------------------------------
    #: How many times a worker has claimed this task.
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    #: Hard cap on claims. Only transient errors are retried.
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=2, server_default="2"
    )
    #: When the current worker's claim expires. An expired lease means the
    #: worker died; the task becomes claimable again.
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: Earliest time a retry may be claimed (backoff).
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: First time a worker actually started it (distinct from created_at).
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: Machine-readable failure reason: model_timeout, model_transient,
    #: citation_invalid, budget_exhausted, interrupted, crashed, ...
    error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    report_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("investigation_reports.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class InvestigationToolCall(Base):
    """A sanitized record of one tool invocation made by the agent.

    Arguments and results are stored as summaries: raw event payloads and model
    prompts are never persisted here.
    """

    __tablename__ = "investigation_tool_calls"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ok', 'error', 'timeout', 'denied', 'invalid')",
            name="ck_investigation_tool_calls_status",
        ),
        Index(
            "ix_investigation_tool_calls_investigation",
            "investigation_id",
            "sequence",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    investigation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("investigations.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Which attempt produced this call (a task may be retried).
    attempt_index: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    arguments: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    result_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=func.now(),
    )


class InvestigationRound(Base):
    """One model turn inside an investigation.

    This is the observability record that the tool-call log cannot provide: it
    answers "which round did the model stall in, and how long did it take?".
    Only metadata is stored - never the prompt, the raw model response, or any
    log content the model may have seen.
    """

    __tablename__ = "investigation_rounds"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('tool_calls', 'findings', 'error', 'budget_exhausted')",
            name="ck_investigation_rounds_outcome",
        ),
        CheckConstraint(
            "round_index >= 1",
            name="ck_investigation_rounds_index",
        ),
        UniqueConstraint(
            "investigation_id",
            "attempt_index",
            "round_index",
            name="uq_investigation_rounds_attempt_index",
        ),
        Index(
            "ix_investigation_rounds_investigation",
            "investigation_id",
            "attempt_index",
            "round_index",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    investigation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("investigations.id", ondelete="CASCADE"),
        nullable=False,
    )
    round_index: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Which attempt produced this round. Attempt 1 and a retry both start at
    #: round 1, so the pair (attempt_index, round_index) is what stays unique.
    attempt_index: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    tool_call_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=func.now(),
    )
