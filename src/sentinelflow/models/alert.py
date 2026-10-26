"""Alert ORM model and its evidence association table."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sentinelflow.core.time import utcnow
from sentinelflow.db.session import Base

if TYPE_CHECKING:
    from sentinelflow.models.security_event import SecurityEvent


alert_events = Table(
    "alert_events",
    Base.metadata,
    Column(
        "alert_id",
        Uuid,
        ForeignKey("alerts.id", ondelete="RESTRICT"),
        primary_key=True,
    ),
    Column(
        "event_id",
        Uuid,
        ForeignKey("security_events.event_id", ondelete="RESTRICT"),
        primary_key=True,
    ),
    Column(
        "linked_at",
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=func.now(),
    ),
    Index("ix_alert_events_event_id", "event_id"),
)


class Alert(Base):
    """A deterministic detection result with links to its evidence events."""

    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('info', 'low', 'medium', 'high', 'critical')",
            name="ck_alerts_severity",
        ),
        CheckConstraint(
            "status IN ('open', 'acknowledged', 'investigating', 'closed')",
            name="ck_alerts_status",
        ),
        UniqueConstraint("dedup_key", name="uq_alerts_dedup_key"),
        Index("ix_alerts_status_created_at", "status", "created_at"),
        Index("ix_alerts_severity_created_at", "severity", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    rule_id: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dedup_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=func.now(),
    )

    evidence_events: Mapped[list["SecurityEvent"]] = relationship(
        secondary=alert_events,
        back_populates="alerts",
    )
