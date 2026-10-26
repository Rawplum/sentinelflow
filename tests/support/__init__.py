"""Shared test doubles and helpers.

The scripted model client lives here (not in the application package) so that
tests and the evaluation harness use one implementation. Production code has no
mock model: the real client is only replaced at the FastAPI dependency boundary.
"""

from __future__ import annotations

import uuid
from typing import Any, TypedDict

from fastapi import FastAPI
from sqlalchemy.orm import sessionmaker

from sentinelflow.ai.model_client import (
    AgentFindings,
    ModelClientError,
    ModelTurn,
)
from sentinelflow.api.routes.investigations import provide_model_client
from sentinelflow.services.reports import load_alert_evidence


class ScriptedClient:
    """Returns pre-scripted turns and records what it was given."""

    provider = "mock"
    model = "mock-investigator"

    def __init__(self, turns: list[ModelTurn | BaseException]) -> None:
        self._turns = turns
        self.calls = 0
        self.system_prompts: list[str] = []
        self.transcripts: list[list[dict[str, Any]]] = []
        self.tool_definitions: list[dict[str, Any]] = []

    def complete(self, *, system_prompt, transcript, tools) -> ModelTurn:
        self.system_prompts.append(system_prompt)
        self.transcripts.append(list(transcript))
        self.tool_definitions = tools
        index = min(self.calls, len(self._turns) - 1)
        self.calls += 1
        turn = self._turns[index]
        # An Exception entry simulates a provider failure for that turn.
        if isinstance(turn, BaseException):
            raise turn
        return turn


class FailingClient:
    """Raises on every call, simulating a provider error or timeout."""

    provider = "mock"
    model = "mock-investigator"

    def __init__(self, message: str = "Model request failed: URLError") -> None:
        self.message = message
        self.calls = 0

    def complete(self, **_kwargs) -> ModelTurn:
        self.calls += 1
        raise ModelClientError(self.message)


def install(app, client) -> None:
    """Point the investigation endpoint at a scripted client."""
    app.dependency_overrides[provide_model_client] = lambda: client


# --- queue draining ---------------------------------------------------------
#
# Tests run with AGENT_WORKER_ENABLED=false so nothing depends on thread
# timing. They drain the durable queue explicitly, through the same
# claim/execute code the worker uses.


class _Configured(TypedDict):
    """The app and session factory the test fixtures hand to the worker."""

    app: FastAPI | None
    session_factory: sessionmaker | None


_configured: _Configured = {"app": None, "session_factory": None}


def configure(app, session_factory) -> None:
    """Register the app and session factory used by :func:`drain_pending`."""
    _configured["app"] = app
    _configured["session_factory"] = session_factory


def drain_pending(limit: int = 50) -> int:
    """Process every claimable task. Returns how many were executed."""
    from sentinelflow.ai.model_client import build_model_client
    from sentinelflow.core.config import get_settings
    from sentinelflow.services.investigation_worker import process_one

    app: FastAPI | None = _configured["app"]
    factory = _configured["session_factory"]
    if app is None or factory is None:
        raise RuntimeError("support.configure(app, session_factory) was not called")

    provider = app.dependency_overrides.get(provide_model_client)
    client = provider() if provider else build_model_client()

    settings = get_settings()
    processed = 0
    while processed < limit:
        with factory() as session:
            result = process_one(
                session,
                client=client,
                lease_seconds=settings.agent_lease_seconds,
                max_rounds=settings.agent_max_rounds,
                max_tool_calls=settings.agent_max_tool_calls,
                tool_timeout_seconds=settings.agent_tool_timeout_seconds,
            )
        if result is None:
            break
        processed += 1
    return processed


def run_via_api(client, alert_id) -> dict:
    """Start an investigation through the API and return its terminal state.

    The endpoint returns 202 with status 'running'; TestClient waits for the
    background task before returning, so one GET is enough to read the outcome.
    """
    created = client.post(f"/api/v1/alerts/{alert_id}/investigations")
    assert created.status_code == 202, created.text
    assert created.json()["status"] == "pending"
    investigation_id = created.json()["id"]
    # Run the durable queue by hand: deterministic, no thread timing.
    drain_pending()
    final = client.get(f"/api/v1/investigations/{investigation_id}")
    assert final.status_code == 200, final.text
    return final.json()


def evidence_ids(session_factory, alert_id) -> list[uuid.UUID]:
    with session_factory() as session:
        return [
            event.event_id
            for event in load_alert_evidence(session, alert_id, limit=100, offset=0)
        ]


def findings(cited: list[uuid.UUID], **overrides) -> AgentFindings:
    payload = {
        "summary": "Five failed logins from one source against one account.",
        "risk_level": "high",
        "reasoning": "The burst matches the AUTH-001 threshold and no success followed.",
        "recommended_actions": ["Contact the account owner."],
        "limitations": ["Only imported authentication events were available."],
        "cited_event_ids": cited,
    }
    payload.update(overrides)
    return AgentFindings.model_validate(payload)


__all__ = [
    "FailingClient",
    "ScriptedClient",
    "configure",
    "drain_pending",
    "evidence_ids",
    "findings",
    "install",
    "run_via_api",
]
