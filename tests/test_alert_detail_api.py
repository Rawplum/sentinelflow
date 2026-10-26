"""Alert detail endpoint tests."""

import uuid

from fastapi.testclient import TestClient


def test_alert_detail_returns_full_alert(admin_client, alert_factory) -> None:
    alert_id = alert_factory(evidence_count=5)

    response = admin_client.get(f"/api/v1/alerts/{alert_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(alert_id)
    assert body["rule_id"] == "AUTH-001"
    assert body["rule_version"] == "1.0.0"
    assert body["title"] == "Suspicious login activity"
    assert body["severity"] == "high"
    assert body["status"] == "open"
    assert body["event_count"] == 5
    assert body["evidence_count"] == 5
    assert body["status_history"] == []


def test_alert_detail_is_readable_by_analyst(
    analyst_client: TestClient, alert_factory
) -> None:
    alert_id = alert_factory(evidence_count=3)

    response = analyst_client.get(f"/api/v1/alerts/{alert_id}")

    assert response.status_code == 200
    assert response.json()["evidence_count"] == 3


def test_alert_detail_unknown_alert_returns_404(admin_client) -> None:
    response = admin_client.get(f"/api/v1/alerts/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Alert not found"


def test_alert_detail_invalid_uuid_returns_422(admin_client) -> None:
    response = admin_client.get("/api/v1/alerts/not-a-uuid")

    assert response.status_code == 422


def test_alert_detail_requires_authentication(client: TestClient) -> None:
    response = client.get(f"/api/v1/alerts/{uuid.uuid4()}")

    assert response.status_code == 401


def test_alert_detail_matches_list_entry(admin_client, alert_factory) -> None:
    alert_id = alert_factory(evidence_count=7)

    listed = admin_client.get("/api/v1/alerts").json()["items"][0]
    detail = admin_client.get(f"/api/v1/alerts/{alert_id}").json()

    assert listed["id"] == detail["id"]
    assert listed["evidence_count"] == detail["evidence_count"]
    assert listed["status"] == detail["status"]
    assert listed["event_count"] == detail["event_count"]
