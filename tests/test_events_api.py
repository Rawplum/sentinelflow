import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from sentinelflow.models.security_event import SecurityEvent
from sentinelflow.schemas.events import SecurityEventCreate
from sentinelflow.services.events import import_events


def test_import_returns_counts(admin_client, event_factory) -> None:
    events = [event_factory(event_id=uuid.uuid4()) for _ in range(2)]

    response = admin_client.post("/api/v1/events/import", json={"events": events})

    assert response.status_code == 201
    body = response.json()
    assert body["received"] == 2
    assert body["imported"] == 2
    assert body["skipped"] == 0
    assert body["skipped_event_ids"] == []


def test_duplicate_import_is_idempotent(admin_client, event_factory) -> None:
    events = [event_factory(event_id=uuid.uuid4()) for _ in range(2)]

    first = admin_client.post("/api/v1/events/import", json={"events": events})
    second = admin_client.post("/api/v1/events/import", json={"events": events})

    assert first.status_code == 201
    assert first.json()["imported"] == 2
    assert second.status_code == 201
    assert second.json()["received"] == 2
    assert second.json()["imported"] == 0
    assert second.json()["skipped"] == 2


def test_duplicate_event_id_within_batch_is_skipped(
    admin_client, event_factory
) -> None:
    event_id = uuid.uuid4()
    events = [
        event_factory(event_id=event_id),
        event_factory(event_id=event_id, raw_message="duplicate retry"),
    ]

    response = admin_client.post("/api/v1/events/import", json={"events": events})

    assert response.status_code == 201
    body = response.json()
    assert body["received"] == 2
    assert body["imported"] == 1
    assert body["skipped"] == 1
    assert body["skipped_event_ids"] == [str(event_id)]


def test_event_list_pagination_and_order(admin_client, event_factory) -> None:
    start = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)
    events = [
        event_factory(
            event_id=uuid.uuid4(),
            timestamp=start + timedelta(minutes=index),
            raw_message=f"synthetic event {index}",
        )
        for index in range(3)
    ]
    admin_client.post("/api/v1/events/import", json={"events": events})

    first_page = admin_client.get("/api/v1/events", params={"limit": 2, "offset": 0})
    second_page = admin_client.get("/api/v1/events", params={"limit": 2, "offset": 2})

    assert first_page.status_code == 200
    assert first_page.json()["total"] == 3
    assert first_page.json()["limit"] == 2
    assert first_page.json()["offset"] == 0
    assert len(first_page.json()["items"]) == 2
    assert first_page.json()["items"][0]["raw_message"] == "synthetic event 2"
    assert len(second_page.json()["items"]) == 1


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 201},
        {"offset": -1},
        {"limit": "not-an-int"},
    ],
)
def test_pagination_parameters_are_validated(admin_client, params) -> None:
    response = admin_client.get("/api/v1/events", params=params)

    assert response.status_code == 422
    assert "detail" in response.json()


def _remove_event_type(payload):
    payload.pop("event_type")


def _remove_event_id(payload):
    payload.pop("event_id")


def _naive_timestamp(payload):
    payload["timestamp"] = "2026-10-19 09:00:00"


def _invalid_outcome(payload):
    payload["outcome"] = "maybe"


def _invalid_ip(payload):
    payload["source_ip"] = "999.999.999.999"


def _oversized_message(payload):
    payload["raw_message"] = "x" * 8193


def _empty_event_type(payload):
    payload["event_type"] = ""


def _empty_raw_message(payload):
    payload["raw_message"] = ""


def _unknown_field(payload):
    payload["unexpected"] = "value"


@pytest.mark.parametrize(
    "mutator",
    [
        _remove_event_type,
        _remove_event_id,
        _naive_timestamp,
        _invalid_outcome,
        _invalid_ip,
        _oversized_message,
        _empty_event_type,
        _empty_raw_message,
        _unknown_field,
    ],
)
def test_invalid_events_are_rejected(admin_client, event_factory, mutator) -> None:
    payload = event_factory()
    mutator(payload)

    response = admin_client.post("/api/v1/events/import", json={"events": [payload]})

    assert response.status_code == 422
    assert "detail" in response.json()


def test_empty_import_is_rejected(admin_client) -> None:
    response = admin_client.post("/api/v1/events/import", json={"events": []})

    assert response.status_code == 422


def test_import_over_batch_limit_is_rejected(admin_client, event_factory) -> None:
    events = [event_factory(event_id=uuid.uuid4()) for _ in range(501)]

    response = admin_client.post("/api/v1/events/import", json={"events": events})

    assert response.status_code == 422


def test_event_round_trip_preserves_nullable_fields(
    admin_client, event_factory
) -> None:
    event = event_factory(
        event_id=uuid.uuid4(),
        username=None,
        source_ip="2001:db8::1",
        asset_id=None,
    )

    imported = admin_client.post("/api/v1/events/import", json={"events": [event]})
    listed = admin_client.get("/api/v1/events")

    assert imported.status_code == 201
    item = listed.json()["items"][0]
    assert item["username"] is None
    assert item["asset_id"] is None
    assert item["source_ip"] == "2001:db8::1"


def test_import_persists_exact_event_ids(
    admin_client, event_factory, db_session
) -> None:
    event_id = uuid.uuid4()
    event = event_factory(event_id=event_id)

    admin_client.post("/api/v1/events/import", json={"events": [event]})

    stored = db_session.get(SecurityEvent, event_id)
    assert stored is not None
    assert stored.event_id == event_id
    assert db_session.scalar(select(func.count()).select_from(SecurityEvent)) == 1


def test_import_service_commits_by_default(session_factory, event_factory) -> None:
    payload = SecurityEventCreate.model_validate(event_factory())

    with session_factory() as session:
        result = import_events(session, [payload])

    assert result.imported == 1
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(SecurityEvent)) == 1
