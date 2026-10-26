"""Security event ORM model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sentinelflow.core.time import utcnow
from sentinelflow.db.session import Base

if TYPE_CHECKING:
    from sentinelflow.models.alert import Alert


class SecurityEvent(Base):
    """A normalized security event imported from a synthetic or real source."""

    __tablename__ = "security_events"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('success', 'failure', 'unknown')",
            name="ck_security_events_outcome",
        ),
        CheckConstraint(
            "length(raw_message) <= 8192",
            name="ck_security_events_raw_message_length",
        ),
        Index("ix_security_events_occurred_at", "occurred_at"),
        Index(
            "ix_security_events_type_outcome_occurred_at",
            "event_type",
            "outcome",
            "occurred_at",
        ),
        Index(
            "ix_security_events_user_ip_occurred_at",
            "username",
            "source_ip",
            "occurred_at",
        ),
        Index("ix_security_events_source", "source"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    # The API field is ``timestamp``; the database column is ``occurred_at`` to
    # avoid relying on a type name used as a column identifier.
    timestamp: Mapped[datetime] = mapped_column(
        "occurred_at", DateTime(timezone=True), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    username: Mapped[str | None] = mapped_column(String(255))
    source_ip: Mapped[str | None] = mapped_column(String(45))
    asset_id: Mapped[str | None] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    raw_message: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=func.now(),
    )

    alerts: Mapped[list[Alert]] = relationship(
        secondary="alert_events",
        back_populates="evidence_events",
    )
