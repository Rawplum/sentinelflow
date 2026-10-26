"""Alert status transition tests."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from sentinelflow.models.alert_status_history import AlertStatusHistory
from sentinelflow.models.audit_log import AuditLog


def _patch(client: TestClient, alert_id, status: str, reason: str | None = None):
    payload: dict = {"status": status}
    if reason is not None:
        payload["reason"] = reason
    return client.patch(f"/api/v1/alerts/{alert_id}", json=payload)


def test_open_to_acknowledged_writes_history_and_audit(
    admin_client, alert_factory, session_factory
) -> None:
    alert_id = alert_factory()

    response = _patch(admin_client, alert_id, "acknowledged", reason="triaged")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "acknowledged"
    assert len(body["status_history"]) == 1
    entry = body["status_history"][0]
    assert entry["from_status"] == "open"
    assert entry["to_status"] == "acknowledged"
    assert entry["reason"] == "triaged"
    assert entry["changed_by_username"] == "admin.test"

    with session_factory() as session:
        history = session.scalars(select(AlertStatusHistory)).all()
        assert len(history) == 1
        assert history[0].alert_id == alert_id

        audit = session.scalars(
            select(AuditLog).where(AuditLog.action == "alerts.status_change")
        ).all()
        assert len(audit) == 1
        assert audit[0].resource_id == str(alert_id)
        assert audit[0].details["from_status"] == "open"
        assert audit[0].details["to_status"] == "acknowledged"


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("acknowledged", "investigating"),
        ("acknowledged", "closed"),
        ("investigating", "closed"),
    ],
)
def test_allowed_forward_transitions(
    admin_client, alert_factory, first, second
) -> None:
    alert_id = alert_factory()

    assert _patch(admin_client, alert_id, first).status_code == 200
    response = _patch(admin_client, alert_id, second)

    assert response.status_code == 200
    assert response.json()["status"] == second
    assert len(response.json()["status_history"]) == 2


def test_open_can_go_straight_to_closed(admin_client, alert_factory) -> None:
    alert_id = alert_factory()

    response = _patch(admin_client, alert_id, "closed", reason="false positive")

    assert response.status_code == 200
    assert response.json()["status"] == "closed"


def test_illegal_transition_returns_409(admin_client, alert_factory) -> None:
    alert_id = alert_factory()
    assert _patch(admin_client, alert_id, "acknowledged").status_code == 200

    response = _patch(admin_client, alert_id, "open")

    assert response.status_code == 409
    assert "Illegal status transition" in response.json()["detail"]


def test_investigating_cannot_go_back_to_acknowledged(
    admin_client, alert_factory
) -> None:
    alert_id = alert_factory()
    assert _patch(admin_client, alert_id, "investigating").status_code == 200

    response = _patch(admin_client, alert_id, "acknowledged")

    assert response.status_code == 409


def test_same_status_is_idempotent_noop(admin_client, alert_factory) -> None:
    alert_id = alert_factory()

    response = _patch(admin_client, alert_id, "open")

    assert response.status_code == 200
    assert response.json()["status"] == "open"
    assert response.json()["status_history"] == []


def test_reopen_requires_reason(admin_client, alert_factory) -> None:
    alert_id = alert_factory()
    assert (
        _patch(admin_client, alert_id, "closed", reason="duplicate").status_code == 200
    )

    without_reason = _patch(admin_client, alert_id, "open")
    assert without_reason.status_code == 422
    assert "reason is required" in without_reason.json()["detail"]

    with_reason = _patch(admin_client, alert_id, "open", reason="new evidence")
    assert with_reason.status_code == 200
    assert with_reason.json()["status"] == "open"


def test_unknown_status_value_returns_422(admin_client, alert_factory) -> None:
    alert_id = alert_factory()

    response = _patch(admin_client, alert_id, "resolved")

    assert response.status_code == 422


def test_unexpected_field_returns_422(admin_client, alert_factory) -> None:
    alert_id = alert_factory()

    response = admin_client.patch(
        f"/api/v1/alerts/{alert_id}",
        json={"status": "acknowledged", "assignee": "someone"},
    )

    assert response.status_code == 422


def test_analyst_cannot_change_status(analyst_client, alert_factory) -> None:
    alert_id = alert_factory()

    response = _patch(analyst_client, alert_id, "acknowledged")

    assert response.status_code == 403
    assert response.json()["detail"] == "Forbidden"


def test_status_change_unknown_alert_returns_404(admin_client) -> None:
    response = _patch(admin_client, uuid.uuid4(), "acknowledged")

    assert response.status_code == 404


def test_status_change_requires_authentication(client, alert_factory) -> None:
    alert_id = alert_factory()

    response = _patch(client, alert_id, "acknowledged")

    assert response.status_code == 401
