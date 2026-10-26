"""End-to-end business chain.

One test walks the whole product path through the real HTTP surface:

    login -> import -> detection -> alert detail -> evidence
          -> agent investigation -> report -> finalize -> audit -> logout

The model is a local stub provider (not a real model). Everything else is the
production code path: real client, real HTTP, real database, real background
task.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from sentinelflow.core.config import get_settings
from support import drain_pending


def _failure_events(username: str = "e2e.demo", count: int = 5):
    base = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)
    return [
        {
            "event_id": str(uuid.uuid4()),
            "timestamp": (base + timedelta(minutes=index)).isoformat(),
            "event_type": "authentication",
            "username": username,
            "source_ip": "198.51.100.77",
            "asset_id": "asset-e2e",
            "action": "login",
            "outcome": "failure",
            "raw_message": f"failed password for {username} #{index}",
            "source": "e2e",
        }
        for index in range(count)
    ]


@pytest.fixture()
def stub_model(monkeypatch, stub_provider):
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    monkeypatch.setenv("LLM_MODEL", "stub-model")
    monkeypatch.setenv("LLM_API_BASE", stub_provider.base_url)
    monkeypatch.setenv("LLM_API_KEY", "sk-stub-not-a-real-key")
    get_settings.cache_clear()
    return stub_provider


def test_core_business_chain(client, admin_user, admin_password, stub_model) -> None:
    # --- 1. login ---------------------------------------------------------
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "admin.test", "password": admin_password},
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    assert login.json()["role"] == "admin"
    auth = {"Authorization": f"Bearer {token}"}

    # A token is required for every business call.
    assert client.get("/api/v1/alerts").status_code == 401

    # --- 2. import synthetic logs ----------------------------------------
    events = _failure_events()
    imported = client.post(
        "/api/v1/events/import", json={"events": events}, headers=auth
    )
    assert imported.status_code == 201, imported.text
    assert imported.json()["imported"] == 5

    # Re-importing the same batch must not duplicate rows.
    again = client.post("/api/v1/events/import", json={"events": events}, headers=auth)
    assert again.json()["imported"] == 0
    assert again.json()["skipped"] == 5

    # --- 3. deterministic detection --------------------------------------
    detection = client.post("/api/v1/detections/run", headers=auth)
    assert detection.status_code == 200, detection.text
    assert detection.json()["alerts_created"] == 1
    alert_id = detection.json()["created_alert_ids"][0]

    # --- 4. alert detail --------------------------------------------------
    detail = client.get(f"/api/v1/alerts/{alert_id}", headers=auth)
    assert detail.status_code == 200
    alert = detail.json()
    assert alert["status"] == "open"
    assert alert["event_count"] == 5
    assert alert["evidence_count"] == 5
    assert alert["status_history"] == []
    assert alert["rule_id"] == "AUTH-001"

    # --- 5. evidence ------------------------------------------------------
    evidence = client.get(
        f"/api/v1/alerts/{alert_id}/evidence", params={"limit": 2}, headers=auth
    ).json()
    assert evidence["total"] == 5
    assert len(evidence["items"]) == 2
    assert evidence["items"][0]["raw_message"] is None

    evidence_ids = {
        item["event_id"]
        for item in client.get(
            f"/api/v1/alerts/{alert_id}/evidence",
            params={"limit": 50, "include_raw_message": "true"},
            headers=auth,
        ).json()["items"]
    }
    assert evidence_ids == {event["event_id"] for event in events}

    # --- 6. agent investigation (stub provider, real HTTP) ----------------
    stub_model.queue_tool_call("get_related_events", {"limit": 5})
    stub_model.queue_findings(cited_event_ids=sorted(evidence_ids)[:2])

    started = client.post(
        f"/api/v1/alerts/{alert_id}/investigations", headers=auth
    )
    assert started.status_code == 202, started.text
    assert started.json()["status"] == "pending"
    investigation_id = started.json()["id"]
    drain_pending()

    final = client.get(f"/api/v1/investigations/{investigation_id}", headers=auth)
    assert final.status_code == 200
    investigation = final.json()
    assert investigation["status"] == "succeeded", investigation
    assert investigation["rounds_used"] == 2
    assert investigation["tool_calls_used"] == 1
    assert investigation["report_id"] is not None
    assert investigation["duration_ms"] is not None
    assert [item["outcome"] for item in investigation["rounds"]] == [
        "tool_calls",
        "findings",
    ]

    # --- 7. structured report --------------------------------------------
    report = client.get(
        f"/api/v1/reports/{investigation['report_id']}", headers=auth
    )
    assert report.status_code == 200
    body = report.json()
    assert body["status"] == "draft"
    assert body["generator"] == "agent"
    assert body["content"]["evidence_total"] == 5
    cited = {item["event_id"] for item in body["content"]["evidence"]}
    assert cited and cited <= evidence_ids
    assert body["content"]["recommended_actions"]

    versions = client.get(f"/api/v1/alerts/{alert_id}/reports", headers=auth).json()
    assert versions["total"] == 1
    assert versions["items"][0]["id"] == investigation["report_id"]

    # --- 8. finalize ------------------------------------------------------
    finalized = client.post(
        f"/api/v1/reports/{investigation['report_id']}/finalize", headers=auth
    )
    assert finalized.status_code == 200
    assert finalized.json()["status"] == "finalized"
    assert finalized.json()["finalized_by_username"] == "admin.test"

    # Finalizing twice is a conflict, not a silent overwrite.
    assert (
        client.post(
            f"/api/v1/reports/{investigation['report_id']}/finalize", headers=auth
        ).status_code
        == 409
    )

    # The agent never mutates the alert's own status.
    assert client.get(f"/api/v1/alerts/{alert_id}", headers=auth).json()["status"] == "open"

    # --- 9. audit trail ---------------------------------------------------
    audit = client.get("/api/v1/audit-logs", params={"limit": 200}, headers=auth)
    assert audit.status_code == 200
    actions = {entry["action"] for entry in audit.json()["items"]}
    assert {
        "auth.login",
        "events.import",
        "detections.run",
        "investigations.run",
        "investigations.complete",
        "reports.read",
        "reports.finalize",
    } <= actions

    # --- 10. logout revokes the token ------------------------------------
    assert client.post("/api/v1/auth/logout", headers=auth).status_code == 204
    assert client.get("/api/v1/alerts", headers=auth).status_code == 401


def test_reload_returns_the_same_investigation_and_report(
    client, admin_user, admin_password, stub_model, alert_factory, session_factory
) -> None:
    """A page refresh must be able to rebuild state from the API alone."""
    from support import evidence_ids

    login = client.post(
        "/api/v1/auth/login",
        json={"username": "admin.test", "password": admin_password},
    )
    auth = {"Authorization": f"Bearer {login.json()['access_token']}"}

    alert_id = alert_factory(evidence_count=3)
    cited = evidence_ids(session_factory, alert_id)[:1]
    stub_model.queue_findings(cited_event_ids=[str(cited[0])])

    created = client.post(f"/api/v1/alerts/{alert_id}/investigations", headers=auth)
    investigation_id = created.json()["id"]
    drain_pending()
    first = client.get(f"/api/v1/investigations/{investigation_id}", headers=auth).json()

    # Simulate a reload: only the ids are known, everything is re-fetched.
    second = client.get(f"/api/v1/investigations/{investigation_id}", headers=auth).json()
    alert = client.get(f"/api/v1/alerts/{alert_id}", headers=auth).json()
    report = client.get(f"/api/v1/reports/{first['report_id']}", headers=auth).json()

    assert second["id"] == first["id"]
    assert second["status"] == first["status"] == "succeeded"
    assert second["report_id"] == first["report_id"]
    assert alert["id"] == str(alert_id)
    assert report["content"]["alert_id"] == str(alert_id)


def test_a_new_investigation_is_allowed_after_the_previous_one_finished(
    client, admin_user, admin_password, stub_model, alert_factory
) -> None:
    """The duplicate guard must not lock the alert after a run completes.

    The "already running" window itself is covered by
    ``test_second_investigation_for_a_running_alert_is_rejected``: TestClient
    runs background tasks before returning, so a double POST here would never
    observe the in-flight state.
    """
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "admin.test", "password": admin_password},
    )
    auth = {"Authorization": f"Bearer {login.json()['access_token']}"}

    alert_id = alert_factory(evidence_count=3)

    stub_model.queue_findings(cited_event_ids=[str(uuid.uuid4())])
    first = client.post(f"/api/v1/alerts/{alert_id}/investigations", headers=auth)
    assert first.status_code == 202
    drain_pending()
    # A citation for a random id fails the run, but the task still terminates.
    assert (
        client.get(f"/api/v1/investigations/{first.json()['id']}", headers=auth)
        .json()["status"]
        == "failed"
    )

    stub_model.queue_findings(cited_event_ids=[str(uuid.uuid4())])
    second = client.post(f"/api/v1/alerts/{alert_id}/investigations", headers=auth)

    assert second.status_code == 202
    assert second.json()["id"] != first.json()["id"]
