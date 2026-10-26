"""Login attempt records used for throttling.

The row stores a salted hash of ``username|source_ip`` rather than either value
in plaintext. This keeps the throttling table from becoming a list of attempted
account names, matching the existing audit rule that failed logins never record
the attempted username.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from sentinelflow.core.time import utcnow
from sentinelflow.db.session import Base


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    __table_args__ = (
        Index(
            "ix_login_attempts_subject_attempted",
            "subject_hash",
            "attempted_at",
        ),
        Index(
            "ix_login_attempts_ip_attempted",
            "ip_hash",
            "attempted_at",
        ),
        Index("ix_login_attempts_attempted_at", "attempted_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    subject_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    succeeded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=func.now(),
    )
