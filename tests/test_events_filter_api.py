"""Security event filter and keyword search tests."""

from datetime import UTC, datetime

import pytest


@pytest.fixture()
def seeded_events(admin_client, event_factory):
    events = [
        event_factory(
            event_id="11111111-1111-4111-8111-111111111111",
            timestamp=datetime(2026, 10, 19, 9, 0, tzinfo=UTC),
            event_type="authentication",
            username="alice.demo",
            source_ip="198.51.100.10",
            action="login",
            outcome="failure",
            raw_message="failed password for alice.demo",
        ),
        event_factory(
            event_id="22222222-2222-4222-8222-222222222222",
            timestamp=datetime(2026, 10, 19, 10, 0, tzinfo=UTC),
            event_type="authentication",
            username="bob.demo",
            source_ip="203.0.113.20",
            action="login",
            outcome="success",
            raw_message="accepted password for bob.demo",
        ),
        event_factory(
            event_id="33333333-3333-4333-8333-333333333333",
            timestamp=datetime(2026, 10, 19, 11, 0, tzinfo=UTC),
            event_type="file",
            username="carol.demo",
            source_ip="192.0.2.30",
            action="read",
            outcome="success",
            raw_message="file access 100% complete",
        ),
    ]
    response = admin_client.post("/api/v1/events/import", json={"events": events})
    assert response.status_code == 201
    return events


def test_filter_by_event_type(admin_client, seeded_events) -> None:
    body = admin_client.get(
        "/api/v1/events", params={"event_type": "authentication"}
    ).json()

    assert body["total"] == 2
    assert {item["event_type"] for item in body["items"]} == {"authentication"}


def test_filter_by_username_and_outcome(admin_client, seeded_events) -> None:
    body = admin_client.get(
        "/api/v1/events",
        params={"username": "alice.demo", "outcome": "failure"},
    ).json()

    assert body["total"] == 1
    assert body["items"][0]["username"] == "alice.demo"


def test_filter_by_source_ip_and_action(admin_client, seeded_events) -> None:
    body = admin_client.get(
        "/api/v1/events",
        params={"source_ip": "203.0.113.20", "action": "login"},
    ).json()

    assert body["total"] == 1
    assert body["items"][0]["source_ip"] == "203.0.113.20"


def test_filter_by_time_range_is_inclusive(admin_client, seeded_events) -> None:
    body = admin_client.get(
        "/api/v1/events",
        params={
            "start": "2026-10-19T09:00:00Z",
            "end": "2026-10-19T10:00:00Z",
        },
    ).json()

    assert body["total"] == 2


def test_filter_by_time_range_start_only(admin_client, seeded_events) -> None:
    body = admin_client.get(
        "/api/v1/events", params={"start": "2026-10-19T10:30:00Z"}
    ).json()

    assert body["total"] == 1
    assert body["items"][0]["username"] == "carol.demo"


def test_keyword_search_matches_raw_message(admin_client, seeded_events) -> None:
    body = admin_client.get("/api/v1/events", params={"q": "password"}).json()

    assert body["total"] == 2


def test_keyword_search_is_case_insensitive(admin_client, seeded_events) -> None:
    body = admin_client.get("/api/v1/events", params={"q": "FAILED"}).json()

    assert body["total"] == 1


def test_keyword_search_escapes_like_wildcards(admin_client, seeded_events) -> None:
    # "%" must be treated literally, not as "match everything".
    percent = admin_client.get("/api/v1/events", params={"q": "%"}).json()
    assert percent["total"] == 1
    assert percent["items"][0]["username"] == "carol.demo"

    underscore = admin_client.get("/api/v1/events", params={"q": "_"}).json()
    assert underscore["total"] == 0


def test_combined_filters(admin_client, seeded_events) -> None:
    body = admin_client.get(
        "/api/v1/events",
        params={
            "event_type": "authentication",
            "outcome": "failure",
            "q": "alice",
        },
    ).json()

    assert body["total"] == 1
    assert body["items"][0]["username"] == "alice.demo"


def test_filters_keep_pagination(admin_client, seeded_events) -> None:
    body = admin_client.get(
        "/api/v1/events",
        params={"event_type": "authentication", "limit": 1, "offset": 1},
    ).json()

    assert body["total"] == 2
    assert len(body["items"]) == 1
    assert body["limit"] == 1
    assert body["offset"] == 1


def test_start_after_end_returns_422(admin_client, seeded_events) -> None:
    response = admin_client.get(
        "/api/v1/events",
        params={
            "start": "2026-10-20T00:00:00Z",
            "end": "2026-10-19T00:00:00Z",
        },
    )

    assert response.status_code == 422
    assert "must not be after" in response.json()["detail"]


def test_naive_timestamp_returns_422(admin_client, seeded_events) -> None:
    response = admin_client.get(
        "/api/v1/events", params={"start": "2026-10-19T09:00:00"}
    )

    assert response.status_code == 422


def test_invalid_outcome_returns_422(admin_client, seeded_events) -> None:
    response = admin_client.get("/api/v1/events", params={"outcome": "maybe"})

    assert response.status_code == 422


def test_keyword_too_long_returns_422(admin_client, seeded_events) -> None:
    response = admin_client.get("/api/v1/events", params={"q": "a" * 201})

    assert response.status_code == 422


def test_limit_still_bounded(admin_client, seeded_events) -> None:
    assert admin_client.get("/api/v1/events", params={"limit": 201}).status_code == 422
    assert admin_client.get("/api/v1/events", params={"limit": 0}).status_code == 422


def test_raw_message_can_be_omitted(admin_client, seeded_events) -> None:
    body = admin_client.get(
        "/api/v1/events", params={"include_raw_message": "false"}
    ).json()

    assert body["total"] == 3
    assert all(item["raw_message"] is None for item in body["items"])


def test_raw_message_included_by_default(admin_client, seeded_events) -> None:
    body = admin_client.get("/api/v1/events").json()

    assert all(item["raw_message"] for item in body["items"])


def test_analyst_can_filter_events(analyst_client, seeded_events) -> None:
    body = analyst_client.get("/api/v1/events", params={"event_type": "file"}).json()

    assert body["total"] == 1
