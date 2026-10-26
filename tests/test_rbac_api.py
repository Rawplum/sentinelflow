from sqlalchemy import select

from sentinelflow.models.audit_log import AuditLog


def _create_alert(admin_client, failure_batch):
    batch = failure_batch(count=5)
    imported = admin_client.post(
        "/api/v1/events/import", json={"events": batch}
    )
    assert imported.status_code == 201
    detection = admin_client.post("/api/v1/detections/run")
    assert detection.status_code == 200
    alerts = admin_client.get("/api/v1/alerts")
    assert alerts.status_code == 200
    return alerts.json()["items"][0]["id"], batch


def test_analyst_can_read_allowed_endpoints(
    analyst_client, admin_client, failure_batch
) -> None:
    alert_id, _ = _create_alert(admin_client, failure_batch)

    assert analyst_client.get("/api/v1/events").status_code == 200
    assert analyst_client.get("/api/v1/alerts").status_code == 200
    assert (
        analyst_client.get(f"/api/v1/alerts/{alert_id}/report").status_code
        == 200
    )
    assert analyst_client.get("/api/v1/auth/me").status_code == 200


def test_analyst_cannot_import_events(analyst_client, event_factory) -> None:
    event = event_factory()

    response = analyst_client.post(
        "/api/v1/events/import", json={"events": [event]}
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Forbidden"}


def test_analyst_cannot_run_detection(analyst_client) -> None:
    response = analyst_client.post("/api/v1/detections/run")

    assert response.status_code == 403
    assert response.json() == {"detail": "Forbidden"}


def test_analyst_cannot_read_audit(analyst_client) -> None:
    response = analyst_client.get("/api/v1/audit-logs")

    assert response.status_code == 403
    assert response.json() == {"detail": "Forbidden"}


def test_admin_can_run_management_operations(
    admin_client, failure_batch
) -> None:
    alert_id, _ = _create_alert(admin_client, failure_batch)

    assert admin_client.get("/api/v1/events").status_code == 200
    assert admin_client.get("/api/v1/alerts").status_code == 200
    assert (
        admin_client.get(f"/api/v1/alerts/{alert_id}/report").status_code
        == 200
    )
    assert admin_client.get("/api/v1/audit-logs").status_code == 200


def test_denied_actions_are_audited(
    analyst_client, event_factory, db_session
) -> None:
    event = event_factory()
    assert (
        analyst_client.post(
            "/api/v1/events/import", json={"events": [event]}
        ).status_code
        == 403
    )
    assert analyst_client.post("/api/v1/detections/run").status_code == 403
    assert analyst_client.get("/api/v1/audit-logs").status_code == 403

    db_session.expire_all()
    denied = list(
        db_session.scalars(
            select(AuditLog).where(
                AuditLog.action == "authorization.denied"
            )
        ).all()
    )

    assert len(denied) == 3
    assert {entry.actor_username for entry in denied} == {"analyst.test"}
    assert {entry.outcome for entry in denied} == {"denied"}
    assert {
        entry.resource_id for entry in denied
    } == {"events:import", "detections:run", "audit:read"}


def test_report_view_by_analyst_is_audited(
    analyst_client, admin_client, failure_batch, db_session
) -> None:
    alert_id, _ = _create_alert(admin_client, failure_batch)

    assert (
        analyst_client.get(f"/api/v1/alerts/{alert_id}/report").status_code
        == 200
    )

    db_session.expire_all()
    audit = db_session.scalar(
        select(AuditLog).where(
            AuditLog.action == "reports.view",
            AuditLog.actor_username == "analyst.test",
        )
    )
    assert audit is not None
    assert audit.resource_type == "alert"
    assert audit.resource_id == alert_id
    assert audit.outcome == "success"


def test_admin_audit_access_is_audited(admin_client, db_session) -> None:
    assert admin_client.get("/api/v1/audit-logs").status_code == 200

    db_session.expire_all()
    audit = db_session.scalar(
        select(AuditLog).where(AuditLog.action == "audit.view")
    )
    assert audit is not None
    assert audit.actor_username == "admin.test"
    assert audit.outcome == "success"


def test_there_is_no_user_management_api(admin_client) -> None:
    response = admin_client.post(
        "/api/v1/users",
        json={"username": "other.user", "password": "other-password-123", "role": "admin"},
    )

    assert response.status_code == 404
