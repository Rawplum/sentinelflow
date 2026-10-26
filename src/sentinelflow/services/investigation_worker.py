"""Durable investigation queue.

Why this design: the project runs as a single node with a database it already
owns. A table plus a lease is enough to survive a process restart, and it avoids
adding Redis/Celery for one queue. FastAPI's in-process background tasks are
*not* durable: if the process dies, the task is lost. Here the task row is the
queue entry, so a crash only loses the attempt, not the task.

Guarantees:

- A task is created as ``pending`` and only becomes ``running`` when a worker
  claims it with a lease.
- Claiming is a conditional UPDATE, so two workers cannot claim the same task.
- If the lease expires (worker died), the task is claimable again while
  ``attempt_count < max_attempts``; otherwise it is reaped as ``failed``.
- Nothing can stay ``running`` forever.
"""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timedelta
from typing import Callable

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from sentinelflow.ai.model_client import (
    ModelClient,
    ModelNotConfiguredError,
    build_model_client,
    model_is_configured,
)
from sentinelflow.core.config import get_settings
from sentinelflow.core.time import as_utc, utcnow
from sentinelflow.models.investigation import Investigation
from sentinelflow.services.investigations import (
    execute_investigation,
    terminate_investigation,
)

logger = logging.getLogger(__name__)

#: Error text used when a lease expires and the task cannot be retried.
INTERRUPTED_ERROR = "Investigation was interrupted before it finished"

SessionFactory = Callable[[], Session]


def _claimable(now: datetime):
    """Rows a worker may take right now."""
    return or_(
        (
            (Investigation.status == "pending")
            & (
                Investigation.next_attempt_at.is_(None)
                | (Investigation.next_attempt_at <= now)
            )
        ),
        (
            (Investigation.status == "running")
            & Investigation.lease_expires_at.is_not(None)
            & (Investigation.lease_expires_at < now)
            & (Investigation.attempt_count < Investigation.max_attempts)
        ),
    )


def claim_next(
    session: Session,
    *,
    lease_seconds: int,
    now: datetime | None = None,
) -> Investigation | None:
    """Atomically claim one task, or return None.

    Uses a conditional UPDATE rather than ``SELECT ... FOR UPDATE SKIP LOCKED``
    so the same code works on PostgreSQL and SQLite. The UPDATE re-checks the
    claim condition, so a concurrent worker that got there first wins cleanly.
    """
    now = now or utcnow()
    condition = _claimable(now)

    candidates = list(
        session.scalars(
            select(Investigation.id)
            .where(condition)
            .order_by(Investigation.created_at.asc(), Investigation.id.asc())
            .limit(5)
        ).all()
    )

    for candidate_id in candidates:
        result = session.execute(
            update(Investigation)
            .where(Investigation.id == candidate_id, condition)
            .values(
                status="running",
                attempt_count=Investigation.attempt_count + 1,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
                started_at=func.coalesce(Investigation.started_at, now),
                next_attempt_at=None,
                error=None,
                error_code=None,
            )
        )
        if result.rowcount == 1:
            session.commit()
            return session.get(Investigation, candidate_id)

    session.rollback()
    return None


def reap_expired(
    session: Session,
    *,
    now: datetime | None = None,
) -> list[uuid.UUID]:
    """Fail tasks whose lease expired and that have no attempts left.

    This is what keeps a killed worker from leaving a task ``running`` forever.
    """
    now = now or utcnow()
    stale = list(
        session.scalars(
            select(Investigation).where(
                Investigation.status == "running",
                Investigation.lease_expires_at.is_not(None),
                Investigation.lease_expires_at < now,
                Investigation.attempt_count >= Investigation.max_attempts,
            )
        ).all()
    )

    for investigation in stale:
        terminate_investigation(
            session,
            investigation,
            status="failed",
            error=INTERRUPTED_ERROR,
            error_code="interrupted",
            duration_ms=max(
                int(
                    (
                        now - as_utc(investigation.started_at or investigation.created_at)
                    ).total_seconds()
                    * 1000
                ),
                0,
            ),
        )
    if stale:
        session.commit()
    return [item.id for item in stale]


def process_one(
    session: Session,
    *,
    client: ModelClient,
    lease_seconds: int,
    max_rounds: int,
    max_tool_calls: int,
    tool_timeout_seconds: float,
    now: datetime | None = None,
) -> Investigation | None:
    """Claim and run a single task. Returns None when the queue is empty."""
    reap_expired(session, now=now)
    investigation = claim_next(session, lease_seconds=lease_seconds, now=now)
    if investigation is None:
        return None

    return execute_investigation(
        session,
        investigation.id,
        client=client,
        max_rounds=max_rounds,
        max_tool_calls=max_tool_calls,
        tool_timeout_seconds=tool_timeout_seconds,
        commit=True,
        retry_transient=True,
    )


def run_worker(
    *,
    stop_event: threading.Event,
    session_factory: sessionmaker | Callable[[], Session],
    poll_seconds: float | None = None,
) -> None:
    """Poll the queue until ``stop_event`` is set.

    One thread, one node. The task table is the queue, so a restart resumes from
    whatever is ``pending`` or has an expired lease.
    """
    settings = get_settings()
    interval = poll_seconds if poll_seconds is not None else settings.agent_worker_poll_seconds
    warned_unconfigured = False

    while not stop_event.is_set():
        if not model_is_configured():
            if not warned_unconfigured:
                logger.warning(
                    "Investigation worker is idle: model provider is not configured"
                )
                warned_unconfigured = True
            stop_event.wait(interval)
            continue
        warned_unconfigured = False

        try:
            client = build_model_client()
            with session_factory() as session:
                processed = process_one(
                    session,
                    client=client,
                    lease_seconds=settings.agent_lease_seconds,
                    max_rounds=settings.agent_max_rounds,
                    max_tool_calls=settings.agent_max_tool_calls,
                    tool_timeout_seconds=settings.agent_tool_timeout_seconds,
                )
        except ModelNotConfiguredError:
            stop_event.wait(interval)
            continue
        except Exception:  # noqa: BLE001 - the loop must survive a bad task
            logger.exception("Investigation worker iteration failed")
            stop_event.wait(interval)
            continue

        if processed is None:
            stop_event.wait(interval)


__all__ = [
    "INTERRUPTED_ERROR",
    "claim_next",
    "process_one",
    "reap_expired",
    "run_worker",
]
