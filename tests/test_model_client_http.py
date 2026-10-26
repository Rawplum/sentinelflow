"""Tests for the OpenAI-compatible HTTP client.

A local stub provider stands in for a real model endpoint. This exercises the
code path that no other test covers: building the request, sending it over
HTTP, and parsing the response.

It does **not** verify model quality, and it is not a real model call. A stub
that returns canned JSON can only prove our client handles the wire format
correctly.
"""

from __future__ import annotations

import json
import uuid

import pytest

from sentinelflow.ai.model_client import (
    ModelClientError,
    ModelNotConfiguredError,
    OpenAICompatibleClient,
    build_model_client,
)
from sentinelflow.core.config import get_settings
from support.stub_provider import SLOW, StubProvider, completion


def _client(server: StubProvider, *, timeout: float = 5.0) -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        base_url=server.base_url,
        api_key="sk-stub-not-a-real-key",
        model="stub-model",
        provider="stub",
        timeout=timeout,
    )


_completion = completion


# --- configuration ----------------------------------------------------------


def test_build_client_requires_configuration(monkeypatch) -> None:
    for name in ("LLM_PROVIDER", "LLM_MODEL", "LLM_API_BASE", "LLM_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()

    with pytest.raises(ModelNotConfiguredError):
        build_model_client()


def test_build_client_uses_environment(monkeypatch, stub_provider) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    monkeypatch.setenv("LLM_MODEL", "stub-model")
    monkeypatch.setenv("LLM_API_BASE", stub_provider.base_url)
    monkeypatch.setenv("LLM_API_KEY", "sk-stub-not-a-real-key")
    get_settings.cache_clear()

    client = build_model_client()

    assert client.provider == "stub"
    assert client.model == "stub-model"


# --- request shape ----------------------------------------------------------


def test_request_carries_system_prompt_and_tools(stub_provider) -> None:
    stub_provider.responses.append(
        (
            200,
            _completion(
                {
                    "tool_calls": [
                        {
                            "id": "c1",
                            "function": {"name": "noop", "arguments": "{}"},
                        }
                    ]
                }
            ),
        )
    )

    _client(stub_provider).complete(
        system_prompt="SYSTEM",
        transcript=[{"role": "user", "content": "hello"}],
        tools=[{"type": "function", "function": {"name": "noop"}}],
    )

    sent = stub_provider.requests[0]
    assert sent["path"] == "/v1/chat/completions"
    assert sent["authorization"] == "Bearer sk-stub-not-a-real-key"
    assert sent["body"]["model"] == "stub-model"
    assert sent["body"]["messages"][0] == {"role": "system", "content": "SYSTEM"}
    assert sent["body"]["tools"][0]["function"]["name"] == "noop"
    assert sent["body"]["temperature"] == 0


# --- response parsing -------------------------------------------------------


def test_parses_tool_calls(stub_provider) -> None:
    stub_provider.responses.append(
        (
            200,
            _completion(
                {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": "get_alert_details",
                                "arguments": '{"limit": 3}',
                            },
                        }
                    ],
                }
            ),
        )
    )

    turn = _client(stub_provider).complete(
        system_prompt="s", transcript=[], tools=[]
    )

    assert turn.findings is None
    assert len(turn.tool_calls) == 1
    assert turn.tool_calls[0].name == "get_alert_details"
    assert turn.tool_calls[0].arguments == {"limit": 3}


def test_parses_findings(stub_provider) -> None:
    event_id = str(uuid.uuid4())
    stub_provider.responses.append(
        (
            200,
            _completion(
                {
                    "content": json.dumps(
                        {
                            "summary": "s",
                            "risk_level": "high",
                            "reasoning": "r",
                            "recommended_actions": ["a"],
                            "limitations": ["l"],
                            "cited_event_ids": [event_id],
                        }
                    )
                }
            ),
        )
    )

    turn = _client(stub_provider).complete(
        system_prompt="s", transcript=[], tools=[]
    )

    assert turn.findings is not None
    assert turn.findings.risk_level == "high"
    assert str(turn.findings.cited_event_ids[0]) == event_id


def test_markdown_fenced_findings_are_accepted(stub_provider) -> None:
    payload = {
        "summary": "s",
        "risk_level": "low",
        "reasoning": "r",
        "recommended_actions": ["a"],
        "limitations": ["l"],
        "cited_event_ids": [str(uuid.uuid4())],
    }
    stub_provider.responses.append(
        (200, _completion({"content": f"```json\n{json.dumps(payload)}\n```"}))
    )

    turn = _client(stub_provider).complete(
        system_prompt="s", transcript=[], tools=[]
    )

    assert turn.findings is not None


# --- failure modes ----------------------------------------------------------


def test_invalid_findings_schema_is_rejected(stub_provider) -> None:
    stub_provider.responses.append(
        (200, _completion({"content": json.dumps({"summary": "only summary"})}))
    )

    with pytest.raises(ModelClientError, match="findings schema"):
        _client(stub_provider).complete(system_prompt="s", transcript=[], tools=[])


def test_malformed_tool_arguments_are_rejected(stub_provider) -> None:
    stub_provider.responses.append(
        (
            200,
            _completion(
                {
                    "tool_calls": [
                        {
                            "id": "c1",
                            "function": {"name": "search_events", "arguments": "{oops"},
                        }
                    ]
                }
            ),
        )
    )

    with pytest.raises(ModelClientError, match="not valid JSON"):
        _client(stub_provider).complete(system_prompt="s", transcript=[], tools=[])


def test_empty_message_is_rejected(stub_provider) -> None:
    stub_provider.responses.append((200, _completion({"content": "   "})))

    with pytest.raises(ModelClientError, match="neither tool calls nor content"):
        _client(stub_provider).complete(system_prompt="s", transcript=[], tools=[])


def test_http_error_becomes_client_error_without_leaking_the_key(stub_provider) -> None:
    stub_provider.responses.append((500, {"error": "boom"}))

    with pytest.raises(ModelClientError) as excinfo:
        _client(stub_provider).complete(system_prompt="s", transcript=[], tools=[])

    message = str(excinfo.value)
    assert "sk-stub-not-a-real-key" not in message
    assert "boom" not in message


def test_timeout_becomes_client_error(stub_provider) -> None:
    stub_provider.responses.append((0, 1.5))  # sentinel: sleep past the timeout

    with pytest.raises(ModelClientError, match="Model request failed"):
        _client(stub_provider, timeout=0.2).complete(
            system_prompt="s", transcript=[], tools=[]
        )


# --- end to end through the real HTTP client --------------------------------


def test_full_investigation_through_a_stub_provider(
    app, admin_client, alert_factory, session_factory, stub_provider, monkeypatch
) -> None:
    """No dependency override: the production client talks real HTTP to the stub.

    This is the closest thing to a real provider run that can be done without
    credentials. It proves the request/response contract, the background task and
    the report write all work together. It says nothing about model quality.
    """
    from support import drain_pending, evidence_ids

    alert_id = alert_factory(evidence_count=3)
    evidence = evidence_ids(session_factory, alert_id)

    stub_provider.responses.append(
        (
            200,
            _completion(
                {
                    "tool_calls": [
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {
                                "name": "get_alert_details",
                                "arguments": "{}",
                            },
                        }
                    ]
                }
            ),
        )
    )
    stub_provider.responses.append(
        (
            200,
            _completion(
                {
                    "content": json.dumps(
                        {
                            "summary": "Stub provider reached through the real client.",
                            "risk_level": "medium",
                            "reasoning": "The alert details tool was called once.",
                            "recommended_actions": ["Review manually."],
                            "limitations": ["Stub provider, not a real model."],
                            "cited_event_ids": [str(evidence[0])],
                        }
                    )
                }
            ),
        )
    )

    monkeypatch.setenv("LLM_PROVIDER", "stub")
    monkeypatch.setenv("LLM_MODEL", "stub-model")
    monkeypatch.setenv("LLM_API_BASE", stub_provider.base_url)
    monkeypatch.setenv("LLM_API_KEY", "sk-stub-not-a-real-key")
    get_settings.cache_clear()

    created = admin_client.post(f"/api/v1/alerts/{alert_id}/investigations")
    assert created.status_code == 202, created.text
    drain_pending()

    final = admin_client.get(f"/api/v1/investigations/{created.json()['id']}")
    body = final.json()

    assert body["status"] == "succeeded", body
    assert body["model_provider"] == "stub"
    assert body["report_id"] is not None
    assert body["rounds_used"] == 2
    assert len(stub_provider.requests) == 2
    assert all(
        request["authorization"] == "Bearer sk-stub-not-a-real-key"
        for request in stub_provider.requests
    )
    assert all(
        request["path"] == "/v1/chat/completions"
        for request in stub_provider.requests
    )
