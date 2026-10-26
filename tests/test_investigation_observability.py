"""Observability tests for the investigation trace.

Covers what the tool-call log alone cannot answer: which model round failed, how
long each round and tool took, whether a request can be correlated, and whether
an interrupted task ever gets stuck in 'running'.
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from sentinelflow.ai.model_client import ModelTurn, ToolCallRequest
from sentinelflow.core.time import utcnow
from sentinelflow.models.investigation import Investigation, InvestigationRound
from sentinelflow.services.investigations import STALE_ERROR
from support import (
    FailingClient,
    ScriptedClient,
    drain_pending,
)
from support import (
    evidence_ids as _evidence_ids,
)
from support import (
    findings as _findings,
)
from support import (
    install as _install,
)
from support import (
    run_via_api as _run,
)


def test_rounds_are_persisted_in_order(
    app, admin_client, alert_factory, session_factory
) -> None:
    alert_id = alert_factory(evidence_count=5)
    cited = _evidence_ids(session_factory, alert_id)[:2]
    _install(
        app,
        ScriptedClient(
            [
                ModelTurn(
                    tool_calls=[
                        ToolCallRequest(
                            call_id="c1", name="get_alert_details", arguments={}
                        )
                    ]
                ),
                ModelTurn(
                    tool_calls=[
                        ToolCallRequest(
                            call_id="c2",
                            name="get_related_events",
                            arguments={"limit": 5},
                        )
                    ]
                ),
                ModelTurn(findings=_findings(cited)),
            ]
        ),
    )

    body = _run(admin_client, alert_id)

    assert body["status"] == "succeeded"
    rounds = body["rounds"]
    assert [item["round_index"] for item in rounds] == [1, 2, 3]
    assert [item["outcome"] for item in rounds] == [
        "tool_calls",
        "tool_calls",
        "findings",
    ]
    assert [item["tool_call_count"] for item in rounds] == [1, 1, 0]
    assert all(item["latency_ms"] >= 0 for item in rounds)
    assert all(item["error"] is None for item in rounds)


def test_model_failure_is_visible_as_an_error_round(
    app, admin_client, alert_factory, session_factory
) -> None:
    alert_id = alert_factory()
    _install(app, FailingClient("Model request failed: TimeoutError"))

    body = _run(admin_client, alert_id)

    assert body["status"] == "failed"
    assert len(body["rounds"]) == 1
    assert body["rounds"][0]["outcome"] == "error"
    assert "TimeoutError" in body["rounds"][0]["error"]


def test_tool_budget_round_is_marked(
    app, admin_client, alert_factory, monkeypatch
) -> None:
    from sentinelflow.core.config import get_settings

    monkeypatch.setenv("AGENT_MAX_TOOL_CALLS", "1")
    get_settings.cache_clear()
    alert_id = alert_factory()
    _install(
        app,
        ScriptedClient(
            [
                ModelTurn(
                    tool_calls=[
                        ToolCallRequest(
                            call_id="c1", name="get_alert_details", arguments={}
                        )
                    ]
                ),
                ModelTurn(
                    tool_calls=[
                        ToolCallRequest(
                            call_id="c2", name="get_alert_details", arguments={}
                        )
                    ]
                ),
            ]
        ),
    )

    body = _run(admin_client, alert_id)

    assert body["status"] == "limit_reached"
    outcomes = [item["outcome"] for item in body["rounds"]]
    assert outcomes[-1] == "budget_exhausted"


def test_duration_and_request_id_are_recorded(
    app, admin_client, alert_factory, session_factory
) -> None:
    alert_id = alert_factory()
    cited = _evidence_ids(session_factory, alert_id)[:1]
    _install(app, ScriptedClient([ModelTurn(findings=_findings(cited))]))

    created = admin_client.post(
        f"/api/v1/alerts/{alert_id}/investigations",
        headers={"X-Request-ID": "observability-test-1"},
    )
    investigation_id = created.json()["id"]
    drain_pending()
    body = admin_client.get(f"/api/v1/investigations/{investigation_id}").json()

    assert body["request_id"] == "observability-test-1"
    assert body["duration_ms"] is not None
    assert body["duration_ms"] >= 0
    assert body["completed_at"] is not None


def test_trace_never_contains_raw_log_content(
    app, admin_client, alert_factory, session_factory
) -> None:
    alert_id = alert_factory(evidence_count=5)
    cited = _evidence_ids(session_factory, alert_id)[:2]
    _install(
        app,
        ScriptedClient(
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
                ModelTurn(findings=_findings(cited)),
            ]
        ),
    )

    body = _run(admin_client, alert_id)
    dumped = json.dumps(body, ensure_ascii=False)

    # The fixture writes "synthetic failure N" into raw_message.
    assert "synthetic failure" not in dumped
    # Neither the prompt nor the tool schema may leak into the trace.
    assert "UNTRUSTED DATA" not in dumped
    assert "cited_event_ids" not in dumped


def test_interrupted_investigation_is_recovered_as_failed(
    admin_client, alert_factory, admin_user, session_factory
) -> None:
    alert_id = alert_factory()
    with session_factory() as session:
        investigation = Investigation(
            alert_id=alert_id,
            status="running",
            prompt_version="1.0.0",
            rounds_used=0,
            tool_calls_used=0,
            created_by_user_id=admin_user.id,
            created_by_username=admin_user.username,
            created_at=utcnow() - timedelta(hours=2),
        )
        session.add(investigation)
        session.commit()
        investigation_id = investigation.id

    body = admin_client.get(f"/api/v1/investigations/{investigation_id}").json()

    assert body["status"] == "failed"
    assert body["error"] == STALE_ERROR
    assert body["completed_at"] is not None
    assert body["duration_ms"] > 0

    with session_factory() as session:
        stored = session.get(Investigation, investigation_id)
        assert stored.status == "failed"


def test_fresh_running_investigation_is_not_recovered(
    admin_client, alert_factory, admin_user, session_factory
) -> None:
    alert_id = alert_factory()
    with session_factory() as session:
        investigation = Investigation(
            alert_id=alert_id,
            status="running",
            prompt_version="1.0.0",
            rounds_used=0,
            tool_calls_used=0,
            created_by_user_id=admin_user.id,
            created_by_username=admin_user.username,
        )
        session.add(investigation)
        session.commit()
        investigation_id = investigation.id

    body = admin_client.get(f"/api/v1/investigations/{investigation_id}").json()

    assert body["status"] == "running"


def test_round_records_have_no_orphans(
    app, admin_client, alert_factory, session_factory
) -> None:
    alert_id = alert_factory()
    cited = _evidence_ids(session_factory, alert_id)[:1]
    _install(app, ScriptedClient([ModelTurn(findings=_findings(cited))]))

    body = _run(admin_client, alert_id)
    investigation_id = uuid.UUID(body["id"])

    with session_factory() as session:
        rounds = session.scalars(
            select(InvestigationRound).where(
                InvestigationRound.investigation_id == investigation_id
            )
        ).all()

    assert len(rounds) == len(body["rounds"])
    assert all(round_row.latency_ms >= 0 for round_row in rounds)


def test_cli_fails_closed_without_model_configuration(monkeypatch, capsys) -> None:
    """The debugging CLI must not pretend to run without a model."""
    from sentinelflow.cli.investigate import main
    from sentinelflow.core.config import get_settings

    for name in ("LLM_PROVIDER", "LLM_MODEL", "LLM_API_BASE", "LLM_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()

    exit_code = main(["--alert-id", str(uuid.uuid4())])

    assert exit_code == 2
    assert "not configured" in capsys.readouterr().err


# --- duplicate submission and data hygiene ---------------------------------


def test_second_investigation_for_a_running_alert_is_rejected(
    app, admin_client, alert_factory, admin_user, session_factory
) -> None:
    """A double submit must not create a second investigation or report."""
    alert_id = alert_factory()
    _install(app, ScriptedClient([ModelTurn(findings=_findings([uuid.uuid4()]))]))
    with session_factory() as session:
        session.add(
            Investigation(
                alert_id=alert_id,
                status="running",
                prompt_version="1.0.0",
                rounds_used=0,
                tool_calls_used=0,
                created_by_user_id=admin_user.id,
                created_by_username=admin_user.username,
            )
        )
        session.commit()

    response = admin_client.post(f"/api/v1/alerts/{alert_id}/investigations")

    assert response.status_code == 409
    assert "already running" in response.json()["detail"]

    with session_factory() as session:
        count = len(
            session.scalars(
                select(Investigation).where(Investigation.alert_id == alert_id)
            ).all()
        )
    assert count == 1


def test_stale_running_row_does_not_block_a_new_investigation(
    app, admin_client, alert_factory, admin_user, session_factory
) -> None:
    """A crashed worker must not lock the alert forever."""
    alert_id = alert_factory()
    with session_factory() as session:
        session.add(
            Investigation(
                alert_id=alert_id,
                status="running",
                prompt_version="1.0.0",
                rounds_used=0,
                tool_calls_used=0,
                created_by_user_id=admin_user.id,
                created_by_username=admin_user.username,
                created_at=utcnow() - timedelta(hours=2),
            )
        )
        session.commit()

    cited = _evidence_ids(session_factory, alert_id)[:1]
    _install(app, ScriptedClient([ModelTurn(findings=_findings(cited))]))

    body = _run(admin_client, alert_id)

    assert body["status"] == "succeeded"


def test_executing_the_same_investigation_twice_is_idempotent(
    alert_factory, admin_user, session_factory
) -> None:
    """A duplicate background dispatch must not run the agent twice."""
    from sentinelflow.ai.agent import run_agent as _run_agent  # noqa: F401
    from sentinelflow.services.investigations import (
        execute_investigation,
        list_rounds,
        list_tool_calls,
        run_investigation,
    )

    alert_id = alert_factory(evidence_count=5)
    cited = _evidence_ids(session_factory, alert_id)[:1]
    client = ScriptedClient(
        [
            ModelTurn(
                tool_calls=[
                    ToolCallRequest(
                        call_id="c1", name="get_alert_details", arguments={}
                    )
                ]
            ),
            ModelTurn(findings=_findings(cited)),
        ]
    )

    with session_factory() as session:
        user = session.get(type(admin_user), admin_user.id)
        first = run_investigation(
            session,
            alert_id,
            user=user,
            client=client,
            max_rounds=5,
            max_tool_calls=8,
            tool_timeout_seconds=5,
            commit=True,
        )
        assert first is not None
        rounds_before = len(list_rounds(session, first.id))
        calls_before = len(list_tool_calls(session, first.id))
        status_before = first.status

        again = execute_investigation(
            session,
            first.id,
            client=client,
            max_rounds=5,
            max_tool_calls=8,
            tool_timeout_seconds=5,
            commit=True,
        )

        assert again is not None
        assert again.status == status_before
        assert len(list_rounds(session, first.id)) == rounds_before
        assert len(list_tool_calls(session, first.id)) == calls_before


def test_trace_contains_no_credentials(
    app, admin_client, alert_factory, session_factory
) -> None:
    """Investigation records must never store tokens, passwords or API keys."""
    import json as _json

    from sentinelflow.models.investigation import InvestigationToolCall

    alert_id = alert_factory()
    cited = _evidence_ids(session_factory, alert_id)[:1]
    _install(app, ScriptedClient([ModelTurn(findings=_findings(cited))]))
    token = admin_client.headers["Authorization"].split(" ", 1)[1]

    _run(admin_client, alert_id)

    with session_factory() as session:
        rows: list[Any] = []
        for model in (Investigation, InvestigationRound, InvestigationToolCall):
            rows.extend(
                _json.dumps(
                    {
                        column.name: str(getattr(row, column.name))
                        for column in model.__table__.columns
                    },
                    ensure_ascii=False,
                )
                for row in session.scalars(select(model)).all()
            )

    blob = " ".join(rows)
    assert token not in blob
    assert "admin-password-123" not in blob
    assert "password" not in blob.lower()
    assert "authorization" not in blob.lower()
