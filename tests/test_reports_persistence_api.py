"""Persisted investigation report versioning tests."""

import uuid

from sqlalchemy import func, select

from sentinelflow.models.investigation_report import InvestigationReport


def test_create_report_version_persists_draft(admin_client, alert_factory) -> None:
    alert_id = alert_factory(evidence_count=5)

    response = admin_client.post(f"/api/v1/alerts/{alert_id}/reports")

    assert response.status_code == 201
    body = response.json()
    assert body["alert_id"] == str(alert_id)
    assert body["version"] == 1
    assert body["status"] == "draft"
    assert body["generator"] == "deterministic"
    assert body["generator_version"] == "1.0.0"
    assert body["created_by_username"] == "admin.test"
    assert body["finalized_at"] is None
    assert body["finalized_by_username"] is None
    assert body["evidence_count"] == 5
    assert body["content"]["alert_id"] == str(alert_id)
    assert len(body["content"]["evidence"]) == 5


def test_versions_increment_and_are_listed_newest_first(
    admin_client, alert_factory
) -> None:
    alert_id = alert_factory()

    first = admin_client.post(f"/api/v1/alerts/{alert_id}/reports").json()
    second = admin_client.post(f"/api/v1/alerts/{alert_id}/reports").json()

    assert first["version"] == 1
    assert second["version"] == 2

    listing = admin_client.get(f"/api/v1/alerts/{alert_id}/reports")
    assert listing.status_code == 200
    body = listing.json()
    assert body["total"] == 2
    assert [item["version"] for item in body["items"]] == [2, 1]


def test_read_persisted_report(admin_client, alert_factory) -> None:
    alert_id = alert_factory()
    created = admin_client.post(f"/api/v1/alerts/{alert_id}/reports").json()

    response = admin_client.get(f"/api/v1/reports/{created['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]
    assert response.json()["content"]["summary"] == created["content"]["summary"]


def test_input_snapshot_records_frozen_inputs(
    admin_client, alert_factory, session_factory
) -> None:
    alert_id = alert_factory(evidence_count=3)
    admin_client.post(f"/api/v1/alerts/{alert_id}/reports")

    with session_factory() as session:
        report = session.scalars(select(InvestigationReport)).one()
        snapshot = report.input_snapshot

    assert snapshot["alert"]["id"] == str(alert_id)
    assert snapshot["alert"]["status"] == "open"
    assert snapshot["evidence_total"] == 3
    assert len(snapshot["evidence_ids"]) == 3


def test_finalize_marks_report_finalized(admin_client, alert_factory) -> None:
    alert_id = alert_factory()
    created = admin_client.post(f"/api/v1/alerts/{alert_id}/reports").json()

    response = admin_client.post(f"/api/v1/reports/{created['id']}/finalize")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "finalized"
    assert body["finalized_at"] is not None
    assert body["finalized_by_username"] == "admin.test"


def test_finalized_report_cannot_be_finalized_again(
    admin_client, alert_factory
) -> None:
    alert_id = alert_factory()
    created = admin_client.post(f"/api/v1/alerts/{alert_id}/reports").json()
    admin_client.post(f"/api/v1/reports/{created['id']}/finalize")

    response = admin_client.post(f"/api/v1/reports/{created['id']}/finalize")

    assert response.status_code == 409
    assert "already finalized" in response.json()["detail"]


def test_new_finalized_version_supersedes_previous(
    admin_client, alert_factory
) -> None:
    alert_id = alert_factory()
    v1 = admin_client.post(f"/api/v1/alerts/{alert_id}/reports").json()
    admin_client.post(f"/api/v1/reports/{v1['id']}/finalize")
    v2 = admin_client.post(f"/api/v1/alerts/{alert_id}/reports").json()

    # v2 is a draft, so v1 is still the finalized version at this point.
    assert admin_client.get(f"/api/v1/reports/{v1['id']}").json()["status"] == (
        "finalized"
    )

    admin_client.post(f"/api/v1/reports/{v2['id']}/finalize")

    assert admin_client.get(f"/api/v1/reports/{v1['id']}").json()["status"] == (
        "superseded"
    )
    assert admin_client.get(f"/api/v1/reports/{v2['id']}").json()["status"] == (
        "finalized"
    )


def test_superseded_report_cannot_be_finalized(admin_client, alert_factory) -> None:
    alert_id = alert_factory()
    v1 = admin_client.post(f"/api/v1/alerts/{alert_id}/reports").json()
    admin_client.post(f"/api/v1/reports/{v1['id']}/finalize")
    v2 = admin_client.post(f"/api/v1/alerts/{alert_id}/reports").json()
    admin_client.post(f"/api/v1/reports/{v2['id']}/finalize")

    response = admin_client.post(f"/api/v1/reports/{v1['id']}/finalize")

    assert response.status_code == 409


def test_get_live_report_does_not_persist(
    admin_client, alert_factory, session_factory
) -> None:
    alert_id = alert_factory()

    for _ in range(3):
        assert (
            admin_client.get(f"/api/v1/alerts/{alert_id}/report").status_code == 200
        )

    with session_factory() as session:
        count = session.scalar(select(func.count()).select_from(InvestigationReport))
    assert count == 0


def test_report_audit_actions_recorded(
    admin_client, alert_factory, session_factory
) -> None:
    from sentinelflow.models.audit_log import AuditLog

    alert_id = alert_factory()
    created = admin_client.post(f"/api/v1/alerts/{alert_id}/reports").json()
    admin_client.post(f"/api/v1/reports/{created['id']}/finalize")

    with session_factory() as session:
        actions = set(
            session.scalars(
                select(AuditLog.action).where(
                    AuditLog.action.in_(["reports.create", "reports.finalize"])
                )
            ).all()
        )
    assert actions == {"reports.create", "reports.finalize"}


def test_analyst_can_read_but_not_write_reports(
    analyst_client, alert_factory
) -> None:
    alert_id = alert_factory()

    assert analyst_client.get(f"/api/v1/alerts/{alert_id}/reports").status_code == 200
    assert analyst_client.post(f"/api/v1/alerts/{alert_id}/reports").status_code == 403
    assert (
        analyst_client.post(f"/api/v1/reports/{uuid.uuid4()}/finalize").status_code
        == 403
    )


def test_unknown_alert_returns_404(admin_client) -> None:
    missing = uuid.uuid4()

    assert admin_client.post(f"/api/v1/alerts/{missing}/reports").status_code == 404
    assert admin_client.get(f"/api/v1/alerts/{missing}/reports").status_code == 404


def test_unknown_report_returns_404(admin_client) -> None:
    missing = uuid.uuid4()

    assert admin_client.get(f"/api/v1/reports/{missing}").status_code == 404
    assert admin_client.post(f"/api/v1/reports/{missing}/finalize").status_code == 404
