"""Persisted investigation report versions."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
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

REPORT_STATUSES = ("draft", "finalized", "superseded")
REPORT_GENERATORS = ("deterministic", "agent")


class InvestigationReport(Base):
    """An immutable-once-finalized snapshot of an investigation report.

    ``content`` stores the rendered report, and ``input_snapshot`` stores the
    alert fields and evidence identifiers the report was derived from. Both are
    kept so a finalized report never changes when rules, events, or code evolve.
    """

    __tablename__ = "investigation_reports"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'finalized', 'superseded')",
            name="ck_investigation_reports_status",
        ),
        CheckConstraint(
            "generator IN ('deterministic', 'agent')",
            name="ck_investigation_reports_generator",
        ),
        CheckConstraint(
            "version >= 1",
            name="ck_investigation_reports_version",
        ),
        CheckConstraint(
            "status <> 'finalized' OR finalized_at IS NOT NULL",
            name="ck_investigation_reports_finalized_at",
        ),
        UniqueConstraint(
            "alert_id",
            "version",
            name="uq_investigation_reports_alert_version",
        ),
        Index(
            "ix_investigation_reports_alert_version",
            "alert_id",
            "version",
        ),
        Index("ix_investigation_reports_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    alert_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("alerts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    generator: Mapped[str] = mapped_column(
        String(32), nullable=False, default="deterministic"
    )
    generator_version: Mapped[str] = mapped_column(String(32), nullable=False)
    input_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    content: Mapped[dict] = mapped_column(JSON, nullable=False)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    evidence_truncated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
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
    finalized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finalized_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    finalized_by_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
