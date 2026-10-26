"""Security event import and query services."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sentinelflow.models.security_event import SecurityEvent
from sentinelflow.schemas.events import SecurityEventCreate


@dataclass(frozen=True)
class ImportResult:
    received: int
    imported: int
    skipped: int
    skipped_event_ids: list[uuid.UUID]


def _to_model(event: SecurityEventCreate) -> SecurityEvent:
    return SecurityEvent(
        event_id=event.event_id,
        timestamp=event.timestamp,
        event_type=event.event_type,
        username=event.username,
        source_ip=str(event.source_ip) if event.source_ip is not None else None,
        asset_id=event.asset_id,
        action=event.action,
        outcome=event.outcome,
        raw_message=event.raw_message,
        source=event.source,
    )


def _insert_if_absent(session: Session, event: SecurityEventCreate) -> bool:
    """Insert one event inside a savepoint, returning False on a conflict."""
    if session.get(SecurityEvent, event.event_id) is not None:
        return False
    try:
        with session.begin_nested():
            session.add(_to_model(event))
            session.flush()
        return True
    except IntegrityError:
        return False


def import_events(
    session: Session,
    events: list[SecurityEventCreate],
    *,
    commit: bool = True,
) -> ImportResult:
    """Import validated events idempotently.

    Duplicate ``event_id`` values are skipped rather than rejected so retries are
    safe. API callers pass ``commit=False`` so the route can write an audit entry
    and commit the business action atomically.
    """
    received = len(events)
    unique_events: dict[uuid.UUID, SecurityEventCreate] = {}
    skipped_ids: list[uuid.UUID] = []

    for event in events:
        if event.event_id in unique_events:
            skipped_ids.append(event.event_id)
        else:
            unique_events[event.event_id] = event

    event_ids = list(unique_events)
    existing_ids: set[uuid.UUID] = set()
    if event_ids:
        existing_ids = set(
            session.scalars(
                select(SecurityEvent.event_id).where(
                    SecurityEvent.event_id.in_(event_ids)
                )
            ).all()
        )

    new_payloads: list[SecurityEventCreate] = []
    for event_id, event in unique_events.items():
        if event_id in existing_ids:
            skipped_ids.append(event_id)
        else:
            new_payloads.append(event)

    if not new_payloads:
        if commit:
            session.commit()
        else:
            session.flush()
        return ImportResult(
            received=received,
            imported=0,
            skipped=len(skipped_ids),
            skipped_event_ids=skipped_ids,
        )

    session.add_all([_to_model(event) for event in new_payloads])
    imported = len(new_payloads)
    try:
        session.flush()
    except IntegrityError:
        # A concurrent transaction inserted one of these IDs between the check
        # and the flush. Retry one record at a time inside savepoints so that
        # unrelated events still import and the caller can commit once.
        session.rollback()
        imported = 0
        for event in new_payloads:
            if _insert_if_absent(session, event):
                imported += 1
            else:
                skipped_ids.append(event.event_id)

    if commit:
        session.commit()
    else:
        session.flush()

    return ImportResult(
        received=received,
        imported=imported,
        skipped=len(skipped_ids),
        skipped_event_ids=skipped_ids,
    )


def _escape_like(value: str) -> str:
    """Escape LIKE wildcards so a search term is matched literally."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@dataclass(frozen=True)
class EventFilters:
    """Allow-listed event filters.

    Only the fields listed here can be filtered or searched. There is no
    free-form query language and no user input ever reaches SQL as text.
    """

    event_type: str | None = None
    username: str | None = None
    source_ip: str | None = None
    asset_id: str | None = None
    action: str | None = None
    outcome: str | None = None
    keyword: str | None = None
    start: datetime | None = None
    end: datetime | None = None

    def is_empty(self) -> bool:
        return all(
            value is None
            for value in (
                self.event_type,
                self.username,
                self.source_ip,
                self.asset_id,
                self.action,
                self.outcome,
                self.keyword,
                self.start,
                self.end,
            )
        )


def _apply_filters(statement, filters: EventFilters | None):
    if filters is None or filters.is_empty():
        return statement

    if filters.event_type is not None:
        statement = statement.where(SecurityEvent.event_type == filters.event_type)
    if filters.username is not None:
        statement = statement.where(SecurityEvent.username == filters.username)
    if filters.source_ip is not None:
        statement = statement.where(SecurityEvent.source_ip == filters.source_ip)
    if filters.asset_id is not None:
        statement = statement.where(SecurityEvent.asset_id == filters.asset_id)
    if filters.action is not None:
        statement = statement.where(SecurityEvent.action == filters.action)
    if filters.outcome is not None:
        statement = statement.where(SecurityEvent.outcome == filters.outcome)
    if filters.keyword is not None:
        statement = statement.where(
            SecurityEvent.raw_message.ilike(
                f"%{_escape_like(filters.keyword)}%",
                escape="\\",
            )
        )
    if filters.start is not None:
        statement = statement.where(SecurityEvent.timestamp >= filters.start)
    if filters.end is not None:
        statement = statement.where(SecurityEvent.timestamp <= filters.end)
    return statement


def list_events(
    session: Session,
    *,
    limit: int,
    offset: int,
    filters: EventFilters | None = None,
) -> tuple[list[SecurityEvent], int]:
    count_statement = _apply_filters(
        select(func.count()).select_from(SecurityEvent), filters
    )
    total = session.scalar(count_statement) or 0

    statement = _apply_filters(select(SecurityEvent), filters)
    items = list(
        session.scalars(
            statement.order_by(
                SecurityEvent.timestamp.desc(),
                SecurityEvent.event_id.asc(),
            )
            .limit(limit)
            .offset(offset)
        ).all()
    )
    return items, total
