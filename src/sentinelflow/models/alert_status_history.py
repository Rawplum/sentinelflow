"""Alert status transition history."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from sentinelflow.core.time import utcnow
from sentinelflow.db.session import Base


class AlertStatusHistory(Base):
    """An append-only record of one alert status change."""

    __tablename__ = "alert_status_history"
    __table_args__ = (
        CheckConstraint(
            "to_status IN ('open', 'acknowledged', 'investigating', 'closed')",
            name="ck_alert_status_history_to_status",
        ),
        CheckConstraint(
            "from_status IS NULL OR from_status IN "
            "('open', 'acknowledged', 'investigating', 'closed')",
            name="ck_alert_status_history_from_status",
        ),
        Index(
            "ix_alert_status_history_alert_created",
            "alert_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    alert_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("alerts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    changed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    changed_by_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=func.now(),
    )
