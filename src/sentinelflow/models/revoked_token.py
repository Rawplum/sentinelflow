"""Revoked access token records.

Only the JWT identifier (``jti``) is stored. The token itself is never
persisted, so a database leak cannot be replayed against the API.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
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


class RevokedToken(Base):
    __tablename__ = "revoked_tokens"
    __table_args__ = (
        # Supports cleanup of entries whose token has already expired.
        Index("ix_revoked_tokens_expires_at", "expires_at"),
        Index("ix_revoked_tokens_user_id", "user_id"),
    )

    jti: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=func.now(),
    )
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
