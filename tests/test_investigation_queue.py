"""Durable investigation queue tests.

Covers the behaviours the queue exists for: explicit states, a lease that
expires when a worker dies, bounded retries for transient errors only, and no
path that leaves a task ``running`` forever.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from sentinelflow.ai.model_client import AgentFindings, ModelClientError, ModelTurn, ToolCallRequest
from sentinelflow.core.config import get_settings
from sentinelflow.core.time import utcnow
from sentinelflow.models.investigation import Investigation
from sentinelflow.services.investigation_worker import (
    INTERRUPTED_ERROR,
    claim_next,
    process_one,
    reap_expired,
)
from sentinelflow.services.investigations import create_investigation

from support import ScriptedClient, evidence_ids, findings


def _make_pending(session_factory, alert_id, admin_user, *, max_attempts=2):
    with session_factory() as session:
        user = session.get(type(admin_user), admin_user.id)
        client = ScriptedClient([ModelTurn(findings=findings([uuid.uuid4()]))])
        investigation = create_investigation(
            session, alert_id, user=user, client=client
        )
        investigation.max_attempts = max_attempts
        session.commit()
        return investigation.id


# --- states -----------------------------------------------------------------


def test_new_task_is_pending_and_does_not_call_the_model(
    app, admin_client, alert_factory, session_factory
) -> None:
    """The HTTP request must not run the model: that is what caused timeouts."""
    from support import install

    alert_id = alert_factory()
    client = ScriptedClient([ModelTurn(findings=findings([uuid.uuid4()]))])
    install(app, client)

    created = admin_client.post(f"/api/v1/alerts/{alert_id}/investigations")

    assert created.status_code == 202
    body = created.json()
    assert body["status"] == "pending"
    assert body["attempt_count"] == 0
    assert body["max_attempts"] >= 1
    assert body["started_at"] is None
    assert body["completed_at"] is None
    assert client.calls == 0, "the request must not call the model"


def test_claim_moves_pending_to_running_with_a_lease(
    alert_factory, admin_user, session_factory
) -> None:
    alert_id = alert_factory()
    investigation_id = _make_pending(session_factory, alert_id, admin_user)

    with session_factory() as session:
        claimed = claim_next(session, lease_seconds=60)

    assert claimed is not None
    assert claimed.id == investigation_id
    assert claimed.status == "running"
    assert claimed.attempt_count == 1
    assert claimed.started_at is not None
    assert claimed.lease_expires_at is not None


def test_a_second_claim_finds_nothing(
    alert_factory, admin_user, session_factory
) -> None:
    alert_id = alert_factory()
    _make_pending(session_factory, alert_id, admin_user)

    with session_factory() as session:
        assert claim_next(session, lease_seconds=60) is not None
    with session_factory() as session:
        assert claim_next(session, lease_seconds=60) is None


# --- crash recovery ---------------------------------------------------------


def test_expired_lease_is_reclaimable(
    alert_factory, admin_user, session_factory
) -> None:
    """A worker that died mid-run must not hold the task forever."""
    alert_id = alert_factory()
    investigation_id = _make_pending(session_factory, alert_id, admin_user, max_attempts=3)

    with session_factory() as session:
        claim_next(session, lease_seconds=60)
        investigation = session.get(Investigation, investigation_id)
        # Simulate the worker dying: the lease is now in the past.
        investigation.lease_expires_at = utcnow() - timedelta(seconds=1)
        session.commit()

    with session_factory() as session:
        reclaimed = claim_next(session, lease_seconds=60)

    assert reclaimed is not None
    assert reclaimed.id == investigation_id
    assert reclaimed.attempt_count == 2


def test_expired_lease_without_attempts_left_is_failed(
    alert_factory, admin_user, session_factory
) -> None:
    alert_id = alert_factory()
    investigation_id = _make_pending(session_factory, alert_id, admin_user, max_attempts=1)

    with session_factory() as session:
        claim_next(session, lease_seconds=60)
        investigation = session.get(Investigation, investigation_id)
        investigation.lease_expires_at = utcnow() - timedelta(seconds=1)
        session.commit()

    with session_factory() as session:
        reaped = reap_expired(session)

    assert reaped == [investigation_id]
    with session_factory() as session:
        investigation = session.get(Investigation, investigation_id)
        assert investigation.status == "failed"
        assert investigation.error == INTERRUPTED_ERROR
        assert investigation.error_code == "interrupted"
        assert investigation.completed_at is not None
        assert investigation.lease_expires_at is None


# --- retries ----------------------------------------------------------------


def _client_that_fails(retryable: bool, message: str = "Model request failed: TimeoutError"):
    error = ModelClientError(message, retryable=retryable)
    return ScriptedClient([error])


def test_transient_failure_is_retried_with_backoff(
    alert_factory, admin_user, session_factory, monkeypatch
) -> None:
    monkeypatch.setenv("AGENT_RETRY_BACKOFF_SECONDS", "30")
    get_settings.cache_clear()
    alert_id = alert_factory()
    investigation_id = _make_pending(session_factory, alert_id, admin_user, max_attempts=2)
    client = _client_that_fails(retryable=True)

    with session_factory() as session:
        process_one(
            session,
            client=client,
            lease_seconds=60,
            max_rounds=5,
            max_tool_calls=8,
            tool_timeout_seconds=5,
        )

    with session_factory() as session:
        investigation = session.get(Investigation, investigation_id)
        assert investigation.status == "pending", "transient errors go back to the queue"
        assert investigation.attempt_count == 1
        assert investigation.next_attempt_at is not None
        assert investigation.error_code == "model_timeout"
        assert investigation.completed_at is None

    # Backoff is respected: not claimable yet.
    with session_factory() as session:
        assert claim_next(session, lease_seconds=60) is None

    # ... and claimable once the backoff has passed.
    with session_factory() as session:
        later = utcnow() + timedelta(seconds=31)
        assert claim_next(session, lease_seconds=60, now=later) is not None


def test_retry_is_bounded_by_max_attempts(
    alert_factory, admin_user, session_factory, monkeypatch
) -> None:
    monkeypatch.setenv("AGENT_RETRY_BACKOFF_SECONDS", "0")
    get_settings.cache_clear()
    alert_id = alert_factory()
    investigation_id = _make_pending(session_factory, alert_id, admin_user, max_attempts=2)
    client = _client_that_fails(retryable=True)

    for _ in range(4):  # more loops than attempts: must not loop forever
        with session_factory() as session:
            process_one(
                session,
                client=client,
                lease_seconds=60,
                max_rounds=5,
                max_tool_calls=8,
                tool_timeout_seconds=5,
            )

    with session_factory() as session:
        investigation = session.get(Investigation, investigation_id)
        assert investigation.status == "failed"
        assert investigation.attempt_count == 2
        assert investigation.completed_at is not None


def test_non_retryable_failure_fails_immediately(
    alert_factory, admin_user, session_factory
) -> None:
    """A schema violation is deterministic; retrying would burn tokens."""
    alert_id = alert_factory()
    investigation_id = _make_pending(session_factory, alert_id, admin_user, max_attempts=3)
    client = _client_that_fails(
        retryable=False,
        message="Model output did not match the required findings schema",
    )

    with session_factory() as session:
        process_one(
            session,
            client=client,
            lease_seconds=60,
            max_rounds=5,
            max_tool_calls=8,
            tool_timeout_seconds=5,
        )

    with session_factory() as session:
        investigation = session.get(Investigation, investigation_id)
        assert investigation.status == "failed"
        assert investigation.attempt_count == 1
        assert investigation.next_attempt_at is None
        assert investigation.error_code == "model_invalid_output"


def test_tool_timeout_does_not_retry_the_task(
    alert_factory, admin_user, session_factory
) -> None:
    """Tool timeouts are recorded and recovered in-run; they are not failures."""
    from sentinelflow.ai.tools import TOOL_SPECS, ToolSpec

    alert_id = alert_factory(evidence_count=3)
    investigation_id = _make_pending(session_factory, alert_id, admin_user, max_attempts=2)

    original = TOOL_SPECS["get_related_events"]

    def slow(_context, _params):
        import time

        time.sleep(0.3)
        return {"returned": 0, "events": []}

    TOOL_SPECS["get_related_events"] = ToolSpec(
        name=original.name,
        description=original.description,
        input_model=original.input_model,
        required_permission=original.required_permission,
        handler=slow,
    )
    try:
        with session_factory() as session:
            with session_factory() as read_session:
                ids = evidence_ids(lambda: read_session, alert_id)
            client = ScriptedClient(
                [
                    ModelTurn(
                        tool_calls=[
                            ToolCallRequest(
                                call_id="c1",
                                name="get_related_events",
                                arguments={"limit": 5},
                            )
                        ]
                    ),
                    ModelTurn(findings=findings([ids[0]])),
                ]
            )
            process_one(
                session,
                client=client,
                lease_seconds=60,
                max_rounds=5,
                max_tool_calls=8,
                tool_timeout_seconds=0.05,
            )
    finally:
        TOOL_SPECS["get_related_events"] = original

    with session_factory() as session:
        investigation = session.get(Investigation, investigation_id)
        assert investigation.status == "succeeded"
        assert investigation.attempt_count == 1


# --- duplicate submission ---------------------------------------------------


def test_second_submission_while_pending_is_rejected(
    app, admin_client, alert_factory, session_factory
) -> None:
    from support import install

    alert_id = alert_factory()
    install(app, ScriptedClient([ModelTurn(findings=findings([uuid.uuid4()]))]))

    first = admin_client.post(f"/api/v1/alerts/{alert_id}/investigations")
    second = admin_client.post(f"/api/v1/alerts/{alert_id}/investigations")

    assert first.status_code == 202
    assert second.status_code == 409
    with session_factory() as session:
        rows = session.scalars(
            select(Investigation).where(Investigation.alert_id == alert_id)
        ).all()
    assert len(rows) == 1


def test_pending_task_is_queryable_without_running_it(
    app, admin_client, alert_factory
) -> None:
    from support import install

    alert_id = alert_factory()
    install(app, ScriptedClient([ModelTurn(findings=findings([uuid.uuid4()]))]))
    created = admin_client.post(f"/api/v1/alerts/{alert_id}/investigations").json()

    fetched = admin_client.get(f"/api/v1/investigations/{created['id']}").json()

    assert fetched["status"] == "pending"
    assert fetched["rounds"] == []
    assert fetched["report_id"] is None


# --- durability across processes -------------------------------------------


def test_pending_task_survives_a_process_restart(tmp_path) -> None:
    """The queue lives in the database, not in memory.

    Simulates a restart by dropping the engine and opening a brand new one on
    the same file: the pending task must still be there and still claimable.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from sentinelflow.db.session import Base
    from sentinelflow.models.alert import Alert
    from sentinelflow.models.user import User
    from sentinelflow.core.security import hash_password
    from sentinelflow.core.permissions import UserRole

    db_path = tmp_path / "queue.db"
    url = f"sqlite:///{db_path.as_posix()}"

    # --- process 1: enqueue --------------------------------------------
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as session:
        user = User(
            username="restart.admin",
            password_hash=hash_password("restart-password-123"),
            role=UserRole.ADMIN.value,
            is_active=True,
        )
        session.add(user)
        session.flush()
        alert = Alert(
            rule_id="AUTH-001",
            rule_version="1.0.0",
            title="restart",
            description="restart",
            severity="high",
            status="open",
            first_seen_at=utcnow(),
            last_seen_at=utcnow(),
            event_count=0,
            dedup_key="restart-key",
        )
        session.add(alert)
        session.commit()
        client = ScriptedClient([ModelTurn(findings=findings([uuid.uuid4()]))])
        investigation = create_investigation(
            session, alert.id, user=user, client=client
        )
        session.commit()
        investigation_id = investigation.id
        alert_id = alert.id
    engine.dispose()

    # --- process 2: a fresh engine sees the same task --------------------
    engine2 = create_engine(url)
    factory2 = sessionmaker(bind=engine2, autoflush=False, expire_on_commit=False)
    try:
        with factory2() as session:
            restored = session.get(Investigation, investigation_id)
            assert restored is not None, "the task must outlive the process"
            assert restored.status == "pending"
            assert restored.alert_id == alert_id

        with factory2() as session:
            claimed = claim_next(session, lease_seconds=60)
            assert claimed is not None
            assert claimed.id == investigation_id
            assert claimed.status == "running"
    finally:
        engine2.dispose()
