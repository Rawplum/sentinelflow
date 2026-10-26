"""Time helpers shared by services and schemas."""

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    """Return an aware UTC datetime.

    SQLite drops timezone information even for ``DateTime(timezone=True)``.
    Treat naive values as UTC so the same code works with SQLite test databases
    and PostgreSQL.
    """
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
