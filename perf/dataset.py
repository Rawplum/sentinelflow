"""Deterministic synthetic log data for performance work.

Everything here is generated from a seed. No production log is ever read, and
the same seed produces byte-identical rows, so a measurement can be repeated.

The shape matters as much as the volume:

- **Bursts.** Detection only fires when one username+IP pair produces at least
  five failures inside five minutes. Data that is uniform random produces almost
  no alerts, which would make the detection and report scenarios meaningless.
  So the generator emits bursts of failures, each burst becoming one alert.
- **Noise.** Between bursts it emits successes and single failures from other
  accounts, so filters such as ``outcome=success`` return a realistic slice
  instead of nothing.
- **Bounded cardinality.** Usernames and IPs come from small pools; that is what
  makes ``(username, source_ip)`` grouping and the composite index meaningful.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import insert
from sqlalchemy.orm import Session

from sentinelflow.models.alert import Alert, alert_events
from sentinelflow.models.security_event import SecurityEvent

#: Fixed epoch so a given seed always produces the same timestamps.
BASE_TIME = datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc)

USER_POOL = tuple(f"user{i:03d}.demo" for i in range(200))
IP_POOL = tuple(f"198.51.100.{i}" for i in range(1, 60)) + tuple(
    f"203.0.113.{i}" for i in range(1, 40)
)
ASSET_POOL = tuple(f"asset-{i:02d}" for i in range(20))

#: Namespace for deterministic event ids: the same (seed, index) gives the same
#: uuid, so re-running a measurement cannot silently use different keys.
EVENT_NAMESPACE = uuid.UUID("6f1c8e2a-1b1e-4c1f-9a4e-2f4b6c8d0a11")


@dataclass(frozen=True)
class DatasetSpec:
    """How much data to build."""

    alerts: int = 20
    #: Noise events emitted per alert. Total events is roughly
    #: ``alerts * (burst_size + noise_per_alert)``.
    noise_per_alert: int = 10
    burst_size: int = 6
    seed: int = 20260301

    @property
    def approx_events(self) -> int:
        return self.alerts * (self.burst_size + self.noise_per_alert)


def generate_events(spec: DatasetSpec) -> list[dict]:
    """Build the rows without touching the database."""
    rng = random.Random(spec.seed)
    rows: list[dict] = []
    index = 0

    def event_id() -> uuid.UUID:
        nonlocal index
        value = uuid.uuid5(EVENT_NAMESPACE, f"{spec.seed}:{index}")
        index += 1
        return value

    # One burst every 10 minutes: bursts never overlap, so each produces exactly
    # one alert and the expected alert count equals spec.alerts.
    for burst in range(spec.alerts):
        started = BASE_TIME + timedelta(minutes=burst * 10)
        username = USER_POOL[burst % len(USER_POOL)]
        source_ip = IP_POOL[burst % len(IP_POOL)]

        for attempt in range(spec.burst_size):
            rows.append(
                {
                    "event_id": event_id(),
                    "timestamp": started + timedelta(seconds=20 * attempt),
                    "event_type": "authentication",
                    "username": username,
                    "source_ip": source_ip,
                    "asset_id": ASSET_POOL[burst % len(ASSET_POOL)],
                    "action": "login",
                    "outcome": "failure",
                    "raw_message": f"failed password for {username} attempt {attempt}",
                    "source": "synthetic-perf",
                    "created_at": started,
                }
            )

        for noise in range(spec.noise_per_alert):
            other = USER_POOL[rng.randrange(len(USER_POOL))]
            rows.append(
                {
                    "event_id": event_id(),
                    "timestamp": started + timedelta(seconds=rng.randrange(0, 540)),
                    "event_type": rng.choice(
                        ["authentication", "authentication", "file_access"]
                    ),
                    "username": other,
                    "source_ip": IP_POOL[rng.randrange(len(IP_POOL))],
                    "asset_id": ASSET_POOL[rng.randrange(len(ASSET_POOL))],
                    "action": rng.choice(["login", "login", "read"]),
                    "outcome": rng.choice(
                        ["success", "failure", "success", "success"]
                    ),
                    "raw_message": f"synthetic noise {burst}-{noise} for {other}",
                    "source": "synthetic-perf",
                    "created_at": started,
                }
            )

    return rows


def insert_events(session: Session, rows: list[dict], *, chunk: int = 5000) -> int:
    """Bulk insert. Far cheaper than one ORM add per row at this volume."""
    for start in range(0, len(rows), chunk):
        session.execute(insert(SecurityEvent), rows[start : start + chunk])
    session.commit()
    return len(rows)


def seed_alert(session: Session, *, index: int, events: int, seed: int = 7) -> uuid.UUID:
    """Create one alert with ``events`` linked evidence rows.

    Used for report-size scenarios: an alert with 150 evidence rows exercises
    the report cap without generating 150 bursts.
    """
    rng = random.Random(seed * 1000 + index)
    started = BASE_TIME + timedelta(hours=index)
    username = f"report{index}.demo"
    source_ip = IP_POOL[index % len(IP_POOL)]

    rows = [
        {
            "event_id": uuid.uuid5(EVENT_NAMESPACE, f"alert:{seed}:{index}:{n}"),
            "timestamp": started + timedelta(seconds=n),
            "event_type": "authentication",
            "username": username,
            "source_ip": source_ip,
            "asset_id": ASSET_POOL[index % len(ASSET_POOL)],
            "action": "login",
            "outcome": "failure",
            "raw_message": f"failed password for {username} #{n}",
            "source": "synthetic-perf",
            "created_at": started,
        }
        for n in range(events)
    ]
    session.execute(insert(SecurityEvent), rows)

    alert = Alert(
        rule_id="AUTH-001",
        rule_version="1.0.0",
        title=f"perf alert {index}",
        description=f"{events} synthetic failures for {username}",
        severity="high",
        status="open",
        first_seen_at=rows[0]["timestamp"],
        last_seen_at=rows[-1]["timestamp"],
        event_count=events,
        dedup_key=f"perf-{seed}-{index}-{rng.random():.6f}",
    )
    session.add(alert)
    session.flush()
    session.execute(
        insert(alert_events),
        [{"alert_id": alert.id, "event_id": row["event_id"]} for row in rows],
    )
    session.commit()
    return alert.id


__all__ = [
    "DatasetSpec",
    "generate_events",
    "insert_events",
    "seed_alert",
]
