"""Alert list filtering.

The console needs to narrow the queue by status and severity, so the list
endpoint has to do that server-side rather than filtering a page in the browser
(which would show wrong counts).
"""

from __future__ import annotations


def _ids(response) -> set[str]:
    return {item["id"] for item in response.json()["items"]}


def test_unfiltered_list_returns_everything(admin_client, alert_factory) -> None:
    open_high = alert_factory(status="open", severity="high")
    closed_low = alert_factory(status="closed", severity="low")

    response = admin_client.get("/api/v1/alerts")

    assert response.status_code == 200
    assert response.json()["total"] == 2
    assert _ids(response) == {str(open_high), str(closed_low)}


def test_filter_by_status(admin_client, alert_factory) -> None:
    open_alert = alert_factory(status="open")
    alert_factory(status="closed")

    response = admin_client.get("/api/v1/alerts", params={"status": "open"})

    assert response.json()["total"] == 1
    assert _ids(response) == {str(open_alert)}


def test_filter_by_severity(admin_client, alert_factory) -> None:
    alert_factory(severity="high")
    critical = alert_factory(severity="critical")

    response = admin_client.get("/api/v1/alerts", params={"severity": "critical"})

    assert response.json()["total"] == 1
    assert _ids(response) == {str(critical)}


def test_combined_filters_and_total(admin_client, alert_factory) -> None:
    match = alert_factory(status="acknowledged", severity="medium")
    alert_factory(status="acknowledged", severity="high")
    alert_factory(status="open", severity="medium")

    response = admin_client.get(
        "/api/v1/alerts", params={"status": "acknowledged", "severity": "medium"}
    )

    body = response.json()
    assert body["total"] == 1
    assert _ids(response) == {str(match)}


def test_filters_keep_pagination_consistent(admin_client, alert_factory) -> None:
    for _ in range(3):
        alert_factory(status="open")
    alert_factory(status="closed")

    first = admin_client.get(
        "/api/v1/alerts", params={"status": "open", "limit": 2, "offset": 0}
    ).json()
    second = admin_client.get(
        "/api/v1/alerts", params={"status": "open", "limit": 2, "offset": 2}
    ).json()

    # total reflects the filter, not the whole table
    assert first["total"] == second["total"] == 3
    assert len(first["items"]) == 2
    assert len(second["items"]) == 1
    assert {item["id"] for item in first["items"]} & {
        item["id"] for item in second["items"]
    } == set()


def test_invalid_filter_value_is_rejected(admin_client) -> None:
    assert admin_client.get("/api/v1/alerts", params={"status": "nope"}).status_code == 422
    assert (
        admin_client.get("/api/v1/alerts", params={"severity": "apocalyptic"}).status_code
        == 422
    )


def test_filters_require_read_permission(client) -> None:
    assert client.get("/api/v1/alerts", params={"status": "open"}).status_code == 401
