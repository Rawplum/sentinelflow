"""The deterministic report must describe the evidence accurately.

Two ways it did not:

1. The stated window came from the page of evidence being rendered, not from
   the alert. Any truncated report (the cap is 100 events) therefore claimed a
   narrower window than the alert actually covered, and `?evidence_offset=N`
   shifted the start further.
2. The summary said "N failed authentication attempts" where N was the count of
   linked events, not the count of failures. A rule that links a successful
   login alongside failures would be described wrongly.

Both are silent: the report looks well formed and the numbers are plausible.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sentinelflow.models.alert import Alert, alert_events
from sentinelflow.models.security_event import SecurityEvent

BASE = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)


def test_truncated_report_states_the_whole_alert_window(
    admin_client, alert_factory
) -> None:
    """The default report for a large alert used to end at the cap, not the end."""
    alert_id = alert_factory(evidence_count=150)

    body = admin_client.get(f"/api/v1/alerts/{alert_id}/report").json()

    # The alert spans 150 minutes; the page only shows the first 100.
    first = BASE.isoformat()
    last = (BASE + timedelta(minutes=149)).isoformat()
    assert body["evidence_truncated"] is True
    assert first in body["summary"], body["summary"]
    assert last in body["summary"], body["summary"]


def test_offset_report_still_states_the_whole_alert_window(
    admin_client, alert_factory
) -> None:
    alert_id = alert_factory(evidence_count=6)

    body = admin_client.get(
        f"/api/v1/alerts/{alert_id}/report?evidence_offset=3"
    ).json()

    assert BASE.isoformat() in body["summary"], body["summary"]
    assert (BASE + timedelta(minutes=5)).isoformat() in body["summary"]


def test_successful_logins_are_not_counted_as_failed_attempts(
    admin_client, session_factory
) -> None:
    """4 failures + 1 success must not be summarised as 5 failed attempts."""
    with session_factory() as session:
        events = []
        for index in range(5):
            outcome = "success" if index == 2 else "failure"
            events.append(
                SecurityEvent(
                    event_id=uuid.uuid4(),
                    timestamp=BASE + timedelta(minutes=index),
                    event_type="authentication",
                    username="mixed.demo",
                    source_ip="198.51.100.44",
                    asset_id="asset-01",
                    action="login",
                    outcome=outcome,
                    raw_message=f"synthetic {outcome} {index}",
                    source="synthetic-auth",
                )
            )
        session.add_all(events)
        session.flush()
        alert = Alert(
            rule_id="AUTH-001",
            rule_version="1.0.0",
            title="Mixed outcomes",
            description="4 failures and 1 success",
            severity="high",
            status="open",
            first_seen_at=BASE,
            last_seen_at=BASE + timedelta(minutes=4),
            event_count=5,
            dedup_key=f"mixed-{uuid.uuid4()}",
        )
        session.add(alert)
        session.flush()
        session.execute(
            alert_events.insert(),
            [{"alert_id": alert.id, "event_id": event.event_id} for event in events],
        )
        session.commit()
        alert_id = alert.id

    body = admin_client.get(f"/api/v1/alerts/{alert_id}/report").json()

    summary = body["summary"]
    assert "5 failed" not in summary, summary
    # The failure count must be the real one.
    assert "4" in summary, summary
    assert "failed" in summary
