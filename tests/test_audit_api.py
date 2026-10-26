import json
import uuid

from sqlalchemy import select

from sentinelflow.models.audit_log import AuditLog


def test_admin_can_list_and_filter_audit(admin_client, event_factory) -> None:
    event = event_factory()
    assert (
        admin_client.post("/api/v1/events/import", json={"events": [event]}).status_code
        == 201
    )

    response = admin_client.get(
        "/api/v1/audit-logs",
        params={"limit": 2, "offset": 0},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 2
    assert body["offset"] == 0
    assert body["total"] >= 2
    assert len(body["items"]) <= 2

    filtered = admin_client.get(
        "/api/v1/audit-logs",
        params={"action": "events.import"},
    )
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["action"] == "events.import"


def test_key_actions_are_audited(admin_client, failure_batch, db_session) -> None:
    batch = failure_batch(count=5)
    assert (
        admin_client.post("/api/v1/events/import", json={"events": batch}).status_code
        == 201
    )
    assert admin_client.post("/api/v1/detections/run").status_code == 200
    alert_id = admin_client.get("/api/v1/alerts").json()["items"][0]["id"]
    assert admin_client.get(f"/api/v1/alerts/{alert_id}/report").status_code == 200
    assert admin_client.get("/api/v1/audit-logs").status_code == 200

    db_session.expire_all()
    entries = list(db_session.scalars(select(AuditLog)).all())
    actions = {entry.action for entry in entries}

    assert {
        "auth.login",
        "events.import",
        "detections.run",
        "reports.view",
        "audit.view",
    } <= actions

    report_view = next(entry for entry in entries if entry.action == "reports.view")
    assert report_view.resource_type == "alert"
    assert report_view.resource_id == alert_id
    assert report_view.outcome == "success"


def test_audit_records_do_not_contain_secrets(client, admin_user, db_session) -> None:
    password = "admin-password-123"
    login = client.post(
        "/api/v1/auth/login",
        json={"username": admin_user.username, "password": password},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]

    db_session.expire_all()
    entries = list(db_session.scalars(select(AuditLog)).all())
    serialized = json.dumps(
        [
            {
                "actor_username": entry.actor_username,
                "action": entry.action,
                "details": entry.details,
            }
            for entry in entries
        ]
    )

    assert password not in serialized
    assert token not in serialized
    assert "$argon2id$" not in serialized


def test_login_failure_audit_does_not_store_attempted_username(
    client, admin_user, db_session
) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={
            "username": admin_user.username,
            "password": "wrong-password-123",
        },
    )
    assert response.status_code == 401

    db_session.expire_all()
    audit = db_session.scalar(
        select(AuditLog).where(AuditLog.action == "auth.login_failed")
    )
    assert audit is not None
    assert audit.actor_username is None
    assert audit.details == {"reason": "invalid_credentials"}


def test_request_id_is_recorded_in_audit(client, admin_user, db_session) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": admin_user.username, "password": "admin-password-123"},
        headers={"X-Request-ID": "login-request-1"},
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "login-request-1"

    db_session.expire_all()
    audit = db_session.scalar(select(AuditLog).where(AuditLog.action == "auth.login"))
    assert audit is not None
    assert audit.request_id == "login-request-1"


def test_audit_pagination_and_filter_validation(admin_client) -> None:
    assert (
        admin_client.get("/api/v1/audit-logs", params={"limit": 0}).status_code == 422
    )
    assert (
        admin_client.get("/api/v1/audit-logs", params={"limit": 201}).status_code == 422
    )
    assert (
        admin_client.get("/api/v1/audit-logs", params={"offset": -1}).status_code == 422
    )
    assert (
        admin_client.get("/api/v1/audit-logs", params={"action": "x" * 65}).status_code
        == 422
    )


def test_audit_endpoint_is_read_only(admin_client) -> None:
    assert admin_client.post("/api/v1/audit-logs", json={}).status_code == 405
    assert admin_client.patch(
        f"/api/v1/audit-logs/{uuid.uuid4()}", json={}
    ).status_code in {404, 405}
    assert admin_client.delete(f"/api/v1/audit-logs/{uuid.uuid4()}").status_code in {
        404,
        405,
    }
