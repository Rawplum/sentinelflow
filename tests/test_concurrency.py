"""Concurrency regressions: the two races the perf run found.

Both were real. Under eight simultaneous status updates the history stopped
being a chain, and under six simultaneous POSTs one alert got five
investigations. The cause in both cases was the same shape: read the row,
decide, write, with nothing stopping a second request from reading the same
row in between.

These tests need real concurrent connections. The suite's default SQLite engine
shares a single connection and ignores ``SELECT ... FOR UPDATE``, so it cannot
reproduce either race and cannot verify the fix. They run only against
PostgreSQL, which is the supported deployment target.
"""

from __future__ import annotations

import os
import threading
import uuid

import pytest
from sqlalchemy import select

from sentinelflow.models.alert import Alert
from sentinelflow.models.alert_status_history import AlertStatusHistory
from sentinelflow.models.investigation import Investigation
from sentinelflow.services.alerts import (
    InvalidStatusTransitionError,
    change_status,
)
from sentinelflow.services.investigations import (
    InvestigationConflictError,
    create_investigation,
)

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or ""

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL.startswith(("postgresql://", "postgresql+psycopg://")),
    reason=(
        "needs PostgreSQL: SQLite shares one connection and ignores FOR UPDATE, "
        "so it cannot reproduce the race or prove the fix"
    ),
)


class _UnusedClient:
    """create_investigation stores the client but does not call it."""

    provider = "unused"
    model = "unused"

    def complete(self, **_kwargs):  # pragma: no cover - never reached
        raise AssertionError("the agent must not run in these tests")


def _run_threads(target, count: int) -> list:
    """Run target(index) in `count` threads released at the same instant."""
    results: list = []
    lock = threading.Lock()
    barrier = threading.Barrier(count)

    def wrapper(index: int) -> None:
        barrier.wait()
        try:
            value = target(index)
        except Exception as exc:  # noqa: BLE001 - recorded, asserted by the caller
            value = exc
        with lock:
            results.append(value)

    threads = [threading.Thread(target=wrapper, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results


def test_concurrent_status_updates_produce_a_coherent_history(
    alert_factory, admin_user, session_factory, monkeypatch
) -> None:
    """Invariant check, not a race reproducer.

    This asserts the property that must always hold: the history is a chain and
    its end matches the alert. It passes both with and without the row lock on
    this machine, because the read-decide-write window is microseconds wide.

    The reproduction is ``python -m perf.concurrency``, which drives the same
    path over HTTP with eight clients and six rounds each. There the history
    stopped being a chain ("row ending at 'investigating' is followed by a row
    starting at 'open'") until ``change_status`` took a row lock.
    """
    import time

    from sentinelflow.services import alerts as alerts_module

    # Widen the window anyway: on a slower machine or under load this may start
    # catching regressions on its own.
    original = alerts_module.is_transition_allowed

    def slow(from_status: str, to_status: str) -> bool:
        time.sleep(0.05)
        return original(from_status, to_status)

    monkeypatch.setattr(alerts_module, "is_transition_allowed", slow)

    alert_id = alert_factory()
    targets = ["acknowledged", "investigating", "closed"]

    def attempt(index: int):
        """Several attempts per thread: one round rarely interleaves enough."""
        outcomes = []
        for step in range(4):
            with session_factory() as session:
                user = session.merge(admin_user)
                try:
                    outcomes.append(
                        change_status(
                            session,
                            alert_id,
                            to_status=targets[(index + step) % len(targets)],
                            user=user,
                            commit=True,
                        )
                    )
                except InvalidStatusTransitionError as exc:
                    session.rollback()
                    outcomes.append(exc)
        return outcomes

    results = _run_threads(attempt, 10)

    with session_factory() as session:
        alert = session.get(Alert, alert_id)
        history = list(
            session.scalars(
                select(AlertStatusHistory)
                .where(AlertStatusHistory.alert_id == alert_id)
                .order_by(AlertStatusHistory.created_at, AlertStatusHistory.id)
            ).all()
        )

    flat = [item for batch in results for item in batch]
    # Some attempts lost the race and were rejected; that is correct behaviour.
    assert any(isinstance(item, InvalidStatusTransitionError) for item in flat)
    assert len(history) >= 2

    # The chain must join up: every row continues where the previous one ended.
    assert history, "at least one transition should have been recorded"
    assert history[0].from_status == "open"
    for previous, current in zip(history, history[1:]):
        assert previous.to_status == current.from_status, (
            f"history row ending at '{previous.to_status}' is followed by a row "
            f"starting at '{current.from_status}'"
        )
    assert history[-1].to_status == alert.status


def test_only_one_investigation_can_start_per_alert(
    alert_factory, admin_user, session_factory
) -> None:
    alert_id = alert_factory()

    def attempt(_index: int):
        with session_factory() as session:
            user = session.merge(admin_user)
            try:
                investigation = create_investigation(
                    session,
                    alert_id,
                    user=user,
                    client=_UnusedClient(),
                    request_id=f"race-{uuid.uuid4().hex[:8]}",
                )
                # The service only flushes; the route commits. Without this the
                # lock is released by the rollback on close and every thread
                # sees an empty table.
                session.commit()
                return investigation
            except InvestigationConflictError as exc:
                session.rollback()
                return exc

    results = _run_threads(attempt, 6)

    created = [item for item in results if isinstance(item, Investigation)]
    conflicts = [item for item in results if isinstance(item, InvestigationConflictError)]

    assert len(created) == 1, f"{len(created)} investigations were created for one alert"
    assert len(conflicts) == 5

    with session_factory() as session:
        rows = session.scalars(
            select(Investigation).where(Investigation.alert_id == alert_id)
        ).all()
    assert len(rows) == 1
