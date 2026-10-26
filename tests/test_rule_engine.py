import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from sentinelflow.services.detection import (
    DetectionEvent,
    find_suspicious_login_windows,
)

BASE = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)


def make_event(second: int, **overrides: Any) -> DetectionEvent:
    values: dict[str, Any] = {
        "event_id": uuid.uuid4(),
        "timestamp": BASE + timedelta(seconds=second),
        "username": "alice.demo",
        "source_ip": "198.51.100.10",
        "event_type": "authentication",
        "action": "login",
        "outcome": "failure",
    }
    values.update(overrides)
    return DetectionEvent(**values)


def test_five_failures_within_window_trigger_one_alert_window() -> None:
    windows = find_suspicious_login_windows(
        [make_event(second) for second in (0, 60, 120, 180, 240)]
    )

    assert len(windows) == 1
    assert len(windows[0].events) == 5
    assert windows[0].username == "alice.demo"
    assert windows[0].source_ip == "198.51.100.10"


def test_window_boundary_is_inclusive() -> None:
    windows = find_suspicious_login_windows(
        [make_event(second) for second in (0, 60, 120, 180, 300)]
    )

    assert len(windows) == 1
    assert len(windows[0].events) == 5


def test_event_just_outside_boundary_does_not_trigger() -> None:
    windows = find_suspicious_login_windows(
        [make_event(second) for second in (0, 60, 120, 180, 301)]
    )

    assert windows == []


def test_four_failures_do_not_trigger() -> None:
    assert (
        find_suspicious_login_windows(
            [make_event(second) for second in (0, 60, 120, 180)]
        )
        == []
    )


def test_successful_events_are_not_counted() -> None:
    events = [make_event(second) for second in (0, 60, 120, 180)]
    events.append(make_event(240, outcome="success"))

    assert find_suspicious_login_windows(events) == []


def test_different_usernames_are_not_merged() -> None:
    events = [make_event(second, username="alice.demo") for second in (0, 60, 120)]
    events += [make_event(second, username="bob.demo") for second in (0, 60, 120)]

    assert find_suspicious_login_windows(events) == []


def test_different_source_ips_are_not_merged() -> None:
    events = [make_event(second, source_ip="198.51.100.10") for second in (0, 60, 120)]
    events += [make_event(second, source_ip="203.0.113.20") for second in (0, 60, 120)]

    assert find_suspicious_login_windows(events) == []


def test_out_of_order_events_are_sorted_before_evaluation() -> None:
    events = [make_event(second * 60) for second in (4, 1, 3, 0, 2)]

    windows = find_suspicious_login_windows(events)

    assert len(windows) == 1
    timestamps = [event.timestamp for event in windows[0].events]
    assert timestamps == sorted(timestamps)


def test_repeated_runs_are_deterministic() -> None:
    events = [make_event(second) for second in (0, 60, 120, 180, 240)]

    first = find_suspicious_login_windows(events)
    second = find_suspicious_login_windows(events)

    assert [window.dedup_key for window in first] == [
        window.dedup_key for window in second
    ]
    assert [event.event_id for event in first[0].events] == [
        event.event_id for event in second[0].events
    ]


def test_long_range_failures_do_not_trigger() -> None:
    windows = find_suspicious_login_windows(
        [make_event(second) for second in (0, 300, 600, 900, 1200)]
    )

    assert windows == []


def test_separate_bursts_create_separate_windows() -> None:
    events = [make_event(second) for second in (0, 60, 120, 180, 240)]
    events += [make_event(600 + second) for second in (0, 60, 120, 180, 240)]

    windows = find_suspicious_login_windows(events)

    assert len(windows) == 2
    assert windows[0].first_seen < windows[1].first_seen


def test_nearby_bursts_are_merged_to_avoid_duplicate_alerts() -> None:
    events = [make_event(second) for second in (0, 60, 120, 180, 240)]
    events += [make_event(480 + second) for second in (0, 60, 120, 180, 240)]

    windows = find_suspicious_login_windows(events)

    assert len(windows) == 1
    assert len(windows[0].events) == 10


def test_naive_timestamps_are_treated_as_utc() -> None:
    naive_base = BASE.replace(tzinfo=None)
    events = [
        make_event(
            0,
            timestamp=naive_base + timedelta(seconds=second),
        )
        for second in (0, 60, 120, 180, 240)
    ]

    windows = find_suspicious_login_windows(events)

    assert len(windows) == 1
    assert windows[0].first_seen.tzinfo is not None


def test_dedup_keys_differ_for_different_groups() -> None:
    events = [make_event(second) for second in (0, 60, 120, 180, 240)]
    events += [
        make_event(second, username="bob.demo", source_ip="203.0.113.20")
        for second in (0, 60, 120, 180, 240)
    ]

    windows = find_suspicious_login_windows(events)

    assert len(windows) == 2
    assert windows[0].dedup_key != windows[1].dedup_key


@pytest.mark.parametrize(
    ("window", "threshold"),
    [(timedelta(minutes=5), 0), (timedelta(0), 5), (timedelta(seconds=-1), 5)],
)
def test_invalid_rule_arguments_are_rejected(window, threshold) -> None:
    with pytest.raises(ValueError):
        find_suspicious_login_windows([], window=window, threshold=threshold)
