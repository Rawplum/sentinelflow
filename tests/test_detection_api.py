import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from sentinelflow.db.session import get_db
from sentinelflow.main import create_app
from sentinelflow.models.alert import Alert
from sentinelflow.models.security_event import SecurityEvent


def test_full_import_detection_report_flow(admin_client, failure_batch, event_factory) -> None:
    failures = failure_batch(count=5)
    success = event_factory(
        event_id=uuid.uuid4(),
        timestamp=datetime(2026, 10, 19, 9, 5, tzinfo=timezone.utc),
        outcome="success",
        raw_message="synthetic successful login",
    )
    failure_ids = {event["event_id"] for event in failures}

    imported = admin_client.post(
        "/api/v1/events/import", json={"events": failures + [success]}
    )
    detection = admin_client.post("/api/v1/detections/run")
    alerts = admin_client.get("/api/v1/alerts")

    assert imported.status_code == 201
    assert imported.json()["imported"] == 6
    assert detection.status_code == 200
    assert detection.json()["events_scanned"] == 5
    assert detection.json()["windows_detected"] == 1
    assert detection.json()["alerts_created"] == 1
    assert detection.json()["alerts_skipped_existing"] == 0
    assert len(detection.json()["created_alert_ids"]) == 1

    assert alerts.status_code == 200
    assert alerts.json()["total"] == 1
    alert = alerts.json()["items"][0]
    assert alert["rule_id"] == "AUTH-001"
    assert alert["severity"] == "high"
    assert alert["status"] == "open"
    assert alert["event_count"] == 5
    assert alert["evidence_count"] == 5

    report_response = admin_client.get(f"/api/v1/alerts/{alert['id']}/report")
    assert report_response.status_code == 200
    report = report_response.json()

    assert report["alert_id"] == alert["id"]
    assert report["risk_level"] == "high"
    assert report["summary"].startswith("Rule AUTH-001 identified 5 failed")
    assert len(report["evidence"]) == 5
    assert {item["event_id"] for item in report["evidence"]} == failure_ids
    assert len(report["timeline"]) == 5
    assert [item["timestamp"] for item in report["timeline"]] == sorted(
        item["timestamp"] for item in report["timeline"]
    )
    assert "AUTH-001" in report["reasoning"]
    assert "both window boundaries" in report["reasoning"]
    assert len(report["recommended_actions"]) >= 1
    assert len(report["limitations"]) >= 1
    assert any("does not prove" in item for item in report["limitations"])


def test_report_evidence_ids_exist_in_database(
    admin_client, failure_batch, db_session
) -> None:
    failures = failure_batch(count=5)
    admin_client.post("/api/v1/events/import", json={"events": failures})
    admin_client.post("/api/v1/detections/run")
    alert_id = admin_client.get("/api/v1/alerts").json()["items"][0]["id"]
    report = admin_client.get(f"/api/v1/alerts/{alert_id}/report").json()

    stored_ids = set(db_session.scalars(select(SecurityEvent.event_id)).all())
    evidence_ids = {uuid.UUID(item["event_id"]) for item in report["evidence"]}

    assert evidence_ids <= stored_ids
    assert len(evidence_ids) == 5
    assert db_session.scalar(select(func.count()).select_from(Alert)) == 1


def test_repeated_detection_does_not_create_duplicate_alerts(
    admin_client, failure_batch
) -> None:
    admin_client.post("/api/v1/events/import", json={"events": failure_batch(count=5)})

    first = admin_client.post("/api/v1/detections/run")
    second = admin_client.post("/api/v1/detections/run")

    assert first.json()["alerts_created"] == 1
    assert second.json()["alerts_created"] == 0
    assert second.json()["alerts_skipped_existing"] == 1
    assert admin_client.get("/api/v1/alerts").json()["total"] == 1


def test_existing_alert_is_not_duplicated_when_new_events_arrive(
    admin_client, failure_batch, event_factory
) -> None:
    events = failure_batch(count=5)
    admin_client.post("/api/v1/events/import", json={"events": events})
    admin_client.post("/api/v1/detections/run")

    extra = event_factory(
        event_id=uuid.uuid4(),
        timestamp=datetime(2026, 10, 19, 9, 4, 30, tzinfo=timezone.utc),
    )
    admin_client.post("/api/v1/events/import", json={"events": [extra]})
    second = admin_client.post("/api/v1/detections/run")

    assert second.json()["alerts_created"] == 0
    assert second.json()["alerts_skipped_existing"] == 1
    assert admin_client.get("/api/v1/alerts").json()["total"] == 1


def test_new_separate_burst_creates_a_second_alert(
    admin_client, failure_batch
) -> None:
    first_burst = failure_batch(count=5)
    second_burst = failure_batch(
        count=5,
        start=datetime(2026, 10, 19, 10, 0, tzinfo=timezone.utc),
    )
    admin_client.post(
        "/api/v1/events/import",
        json={"events": first_burst + second_burst},
    )

    detection = admin_client.post("/api/v1/detections/run")

    assert detection.json()["windows_detected"] == 2
    assert detection.json()["alerts_created"] == 2
    assert admin_client.get("/api/v1/alerts").json()["total"] == 2


def test_no_matching_events_returns_zero_counts(admin_client, failure_batch) -> None:
    admin_client.post("/api/v1/events/import", json={"events": failure_batch(count=4)})

    detection = admin_client.post("/api/v1/detections/run")

    assert detection.status_code == 200
    assert detection.json()["events_scanned"] == 4
    assert detection.json()["windows_detected"] == 0
    assert detection.json()["alerts_created"] == 0
    assert admin_client.get("/api/v1/alerts").json()["total"] == 0


def test_different_users_and_ips_are_not_merged(
    admin_client, failure_batch
) -> None:
    first = failure_batch(count=4, username="alice.demo", source_ip="198.51.100.10")
    second = failure_batch(count=4, username="bob.demo", source_ip="203.0.113.20")
    admin_client.post("/api/v1/events/import", json={"events": first + second})

    detection = admin_client.post("/api/v1/detections/run")

    assert detection.json()["alerts_created"] == 0


def test_alert_list_pagination(admin_client, failure_batch) -> None:
    first = failure_batch(count=5, username="alice.demo", source_ip="198.51.100.10")
    second = failure_batch(count=5, username="bob.demo", source_ip="203.0.113.20")
    admin_client.post("/api/v1/events/import", json={"events": first + second})
    admin_client.post("/api/v1/detections/run")

    page = admin_client.get("/api/v1/alerts", params={"limit": 1, "offset": 1})

    assert page.status_code == 200
    assert page.json()["total"] == 2
    assert len(page.json()["items"]) == 1


def test_unknown_alert_report_returns_404(admin_client) -> None:
    response = admin_client.get(f"/api/v1/alerts/{uuid.uuid4()}/report")

    assert response.status_code == 404
    assert response.json() == {"detail": "Alert not found"}


def test_invalid_alert_id_returns_422(admin_client) -> None:
    response = admin_client.get("/api/v1/alerts/not-a-uuid/report")

    assert response.status_code == 422


def test_database_error_returns_generic_500(admin_token) -> None:
    class BrokenSession:
        def get(self, *args, **kwargs):
            raise OperationalError("SELECT 1", {}, Exception("boom"))

        def scalar(self, *args, **kwargs):
            raise OperationalError("SELECT 1", {}, Exception("boom"))

    def broken_db():
        yield BrokenSession()

    app = create_app()
    app.dependency_overrides[get_db] = broken_db
    with TestClient(app, raise_server_exceptions=False) as admin_client:
        admin_client.headers.update(
            {"Authorization": f"Bearer {admin_token}"}
        )
        response = admin_client.get("/api/v1/events")

    assert response.status_code == 500
    assert response.json() == {"detail": "Database operation failed"}
    assert "boom" not in response.text
