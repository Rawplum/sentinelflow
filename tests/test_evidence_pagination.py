"""Report evidence cap and evidence pagination tests."""

import uuid

from sqlalchemy import select

from sentinelflow.models.security_event import SecurityEvent
from sentinelflow.schemas.alerts import MAX_REPORT_EVIDENCE


def test_report_caps_evidence_and_reports_total(admin_client, alert_factory) -> None:
    alert_id = alert_factory(evidence_count=150)

    response = admin_client.get(f"/api/v1/alerts/{alert_id}/report")

    assert response.status_code == 200
    body = response.json()
    assert len(body["evidence"]) == MAX_REPORT_EVIDENCE
    assert body["evidence_total"] == 150
    assert body["evidence_truncated"] is True
    assert len(body["timeline"]) == MAX_REPORT_EVIDENCE
    assert "shows 100 of 150" in body["summary"]


def test_report_below_cap_is_not_truncated(admin_client, alert_factory) -> None:
    alert_id = alert_factory(evidence_count=12)

    body = admin_client.get(f"/api/v1/alerts/{alert_id}/report").json()

    assert len(body["evidence"]) == 12
    assert body["evidence_total"] == 12
    assert body["evidence_truncated"] is False
    assert "shows" not in body["summary"]


def test_report_evidence_limit_and_offset(admin_client, alert_factory) -> None:
    alert_id = alert_factory(evidence_count=40)

    page = admin_client.get(
        f"/api/v1/alerts/{alert_id}/report",
        params={"evidence_limit": 10, "evidence_offset": 30},
    ).json()

    assert len(page["evidence"]) == 10
    assert page["evidence_total"] == 40
    assert page["evidence_truncated"] is False


def test_report_evidence_limit_above_cap_returns_422(
    admin_client, alert_factory
) -> None:
    alert_id = alert_factory()

    response = admin_client.get(
        f"/api/v1/alerts/{alert_id}/report",
        params={"evidence_limit": MAX_REPORT_EVIDENCE + 1},
    )

    assert response.status_code == 422


def test_report_evidence_limit_zero_returns_422(admin_client, alert_factory) -> None:
    alert_id = alert_factory()

    response = admin_client.get(
        f"/api/v1/alerts/{alert_id}/report",
        params={"evidence_limit": 0},
    )

    assert response.status_code == 422


def test_report_evidence_ids_all_exist(
    admin_client, alert_factory, session_factory
) -> None:
    alert_id = alert_factory(evidence_count=150)

    body = admin_client.get(f"/api/v1/alerts/{alert_id}/report").json()
    returned = {uuid.UUID(item["event_id"]) for item in body["evidence"]}

    with session_factory() as session:
        stored = set(session.scalars(select(SecurityEvent.event_id)).all())

    assert returned
    assert returned <= stored


def test_evidence_endpoint_paginates(admin_client, alert_factory) -> None:
    alert_id = alert_factory(evidence_count=30)

    first = admin_client.get(
        f"/api/v1/alerts/{alert_id}/evidence", params={"limit": 10, "offset": 0}
    )
    last = admin_client.get(
        f"/api/v1/alerts/{alert_id}/evidence", params={"limit": 10, "offset": 20}
    )

    assert first.status_code == 200
    assert first.json()["total"] == 30
    assert len(first.json()["items"]) == 10
    assert len(last.json()["items"]) == 10

    first_ids = {item["event_id"] for item in first.json()["items"]}
    last_ids = {item["event_id"] for item in last.json()["items"]}
    assert first_ids.isdisjoint(last_ids)


def test_evidence_endpoint_omits_raw_message_by_default(
    admin_client, alert_factory
) -> None:
    alert_id = alert_factory(evidence_count=3)

    default = admin_client.get(f"/api/v1/alerts/{alert_id}/evidence").json()
    included = admin_client.get(
        f"/api/v1/alerts/{alert_id}/evidence",
        params={"include_raw_message": "true"},
    ).json()

    assert all(item["raw_message"] is None for item in default["items"])
    assert all(item["raw_message"] for item in included["items"])


def test_evidence_endpoint_limit_is_bounded(admin_client, alert_factory) -> None:
    alert_id = alert_factory()

    assert (
        admin_client.get(
            f"/api/v1/alerts/{alert_id}/evidence", params={"limit": 201}
        ).status_code
        == 422
    )
    assert (
        admin_client.get(
            f"/api/v1/alerts/{alert_id}/evidence", params={"limit": 0}
        ).status_code
        == 422
    )


def test_evidence_endpoint_unknown_alert_returns_404(admin_client) -> None:
    response = admin_client.get(f"/api/v1/alerts/{uuid.uuid4()}/evidence")

    assert response.status_code == 404


def test_persisted_report_records_truncation(admin_client, alert_factory) -> None:
    alert_id = alert_factory(evidence_count=130)

    created = admin_client.post(f"/api/v1/alerts/{alert_id}/reports").json()

    assert created["evidence_count"] == 130
    assert created["evidence_truncated"] is True
    assert len(created["content"]["evidence"]) == MAX_REPORT_EVIDENCE
    assert created["content"]["evidence_total"] == 130
