import ipaddress
import json
from pathlib import Path

from pydantic import ValidationError

from sentinelflow.schemas.events import SecurityEventCreate

SAMPLE_PATH = Path(__file__).resolve().parents[1] / "data" / "sample_events.jsonl"
TEST_NETWORKS = [
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
]


def _parse_sample():
    valid: list[SecurityEventCreate] = []
    invalid_lines: list[int] = []
    for line_number, line in enumerate(
        SAMPLE_PATH.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        payload = json.loads(line)
        try:
            valid.append(SecurityEventCreate.model_validate(payload))
        except ValidationError:
            invalid_lines.append(line_number)
    return valid, invalid_lines


def test_sample_file_covers_valid_invalid_and_duplicate_cases() -> None:
    valid, invalid_lines = _parse_sample()
    event_ids = [str(event.event_id) for event in valid]

    assert len(valid) == 25
    assert invalid_lines == [26, 27, 28, 29]
    assert len(set(event_ids)) == 24
    assert len(event_ids) - len(set(event_ids)) == 1


def test_sample_events_are_synthetic_and_use_documentation_ips() -> None:
    valid, _ = _parse_sample()

    for event in valid:
        assert event.source == "synthetic-auth"
        assert event.username is None or event.username.endswith(".demo")
        if event.source_ip is not None:
            address = ipaddress.ip_address(event.source_ip)
            assert any(address in network for network in TEST_NETWORKS)


def test_sample_file_contains_the_expected_bursts() -> None:
    valid, _ = _parse_sample()

    alice_failures = {
        event.event_id: event
        for event in valid
        if event.username == "alice.demo" and event.outcome == "failure"
    }
    dave_failures = {
        event.event_id: event
        for event in valid
        if event.username == "dave.demo"
        and event.outcome == "failure"
        and str(event.source_ip) == "203.0.113.30"
    }

    assert len(alice_failures) == 5
    assert len(dave_failures) == 5
