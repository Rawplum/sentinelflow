"""Fixed synthetic dataset for the benchmark.

Every case is invented: no production logs, no real users. Each case is seeded
into a throwaway database so the same run can be repeated exactly.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from sentinelflow.models.alert import Alert
from sentinelflow.models.security_event import SecurityEvent

CASES_PATH = Path(__file__).resolve().parent / "cases.json"
BASE_TIME = datetime(2026, 3, 2, 9, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class Case:
    id: str
    scenario: str
    description: str
    applicable_to: tuple[str, ...]
    expect: dict[str, Any]
    spec: dict[str, Any]


def load_cases() -> list[Case]:
    raw = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    return [
        Case(
            id=item["id"],
            scenario=item["scenario"],
            description=item["description"],
            applicable_to=tuple(item.get("applicable_to", ())),
            expect=item.get("expect", {}),
            spec=item,
        )
        for item in raw
    ]


def seed(session: Session, case: Case) -> Alert:
    """Create the case's events and the alert that links them."""
    alert_spec = case.spec["alert"]
    username = alert_spec["username"]
    source_ip = alert_spec.get("source_ip", "198.51.100.10")

    events = []
    for index, spec in enumerate(case.spec["events"]):
        offset = int(spec.get("offset_minutes", index))
        events.append(
            SecurityEvent(
                event_id=uuid.uuid4(),
                timestamp=BASE_TIME + timedelta(minutes=offset),
                event_type="authentication",
                username=username,
                source_ip=source_ip,
                asset_id="asset-bench",
                action="login",
                outcome=spec.get("outcome", "failure"),
                raw_message=spec.get("raw_message", f"event {index}"),
                source="benchmark",
            )
        )
    session.add_all(events)

    timestamps = [event.timestamp for event in events]
    alert = Alert(
        rule_id=alert_spec.get("rule_id", "AUTH-001"),
        rule_version="1.0.0",
        title=f"{case.scenario}: {username}",
        description=case.description,
        severity=alert_spec.get("severity", "medium"),
        status="open",
        first_seen_at=min(timestamps),
        last_seen_at=max(timestamps),
        event_count=len(events),
        dedup_key=f"{case.id}-{uuid.uuid4().hex}",
    )
    alert.evidence_events = events
    session.add(alert)
    session.flush()
    return alert


__all__ = ["Case", "load_cases", "seed"]
