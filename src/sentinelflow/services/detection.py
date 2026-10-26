"""Deterministic authentication-failure detection rule."""

from __future__ import annotations

import hashlib
import uuid
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sentinelflow.core.time import as_utc, utcnow
from sentinelflow.models.alert import Alert, alert_events
from sentinelflow.models.security_event import SecurityEvent

RULE_ID = "AUTH-001"
RULE_VERSION = "1.0.0"
AUTH_EVENT_TYPE = "authentication"
AUTH_ACTION = "login"
WINDOW = timedelta(minutes=5)
THRESHOLD = 5
ALERT_SEVERITY = "high"
ALERT_TITLE = "Suspicious login activity"


@dataclass(frozen=True)
class DetectionEvent:
    """Minimal immutable event representation used by the pure rule function."""

    event_id: uuid.UUID
    timestamp: datetime
    username: str
    source_ip: str
    event_type: str
    action: str
    outcome: str


@dataclass(frozen=True)
class DetectionWindow:
    username: str
    source_ip: str
    events: tuple[DetectionEvent, ...]

    @property
    def first_seen(self) -> datetime:
        return self.events[0].timestamp

    @property
    def last_seen(self) -> datetime:
        return self.events[-1].timestamp

    @property
    def dedup_key(self) -> str:
        # The first evidence event is stable for a fixed input set, so re-running
        # detection on the same data produces the same key. Hash the components
        # to keep the key bounded and avoid delimiter ambiguity.
        raw = f"{RULE_ID}|{self.username}|{self.source_ip}|{self.events[0].event_id}"
        return f"{RULE_ID}:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"


@dataclass(frozen=True)
class DetectionRunResult:
    events_scanned: int
    windows_detected: int
    alerts_created: int
    alerts_skipped_existing: int
    created_alert_ids: list[uuid.UUID]


def _is_candidate(event: DetectionEvent) -> bool:
    return (
        event.event_type == AUTH_EVENT_TYPE
        and event.action == AUTH_ACTION
        and event.outcome == "failure"
        and bool(event.username)
        and bool(event.source_ip)
    )


def find_suspicious_login_windows(
    events: list[DetectionEvent],
    *,
    window: timedelta = WINDOW,
    threshold: int = THRESHOLD,
) -> list[DetectionWindow]:
    """Find groups of authentication failures that meet the rule.

    A window starts at an event and includes every event whose timestamp is
    less than or equal to ``start + window`` (both boundaries inclusive). Only
    events with the same username and source IP are considered together.
    Nearby overlapping windows are merged into one detection window so a single
    burst produces one alert. Re-running on the same input is deterministic.
    """
    if threshold < 1:
        raise ValueError("threshold must be at least 1")
    if window <= timedelta(0):
        raise ValueError("window must be positive")

    normalized = [
        replace(event, timestamp=as_utc(event.timestamp))
        for event in events
        if _is_candidate(event)
    ]

    grouped: dict[tuple[str, str], list[DetectionEvent]] = defaultdict(list)
    for event in normalized:
        grouped[(event.username, event.source_ip)].append(event)

    windows: list[DetectionWindow] = []
    for (username, source_ip), group in sorted(grouped.items()):
        group.sort(key=lambda item: (item.timestamp, str(item.event_id)))

        candidates: list[tuple[int, int]] = []
        right = 0
        for left in range(len(group)):
            if right < left:
                right = left
            limit = group[left].timestamp + window
            while right < len(group) and group[right].timestamp <= limit:
                right += 1
            if right - left >= threshold:
                candidates.append((left, right))

        if not candidates:
            continue

        # Merge candidate windows whose bursts are close enough that treating
        # them as one incident avoids duplicate alerts. The gap is measured from
        # the last evidence event of the current cluster.
        merged: list[tuple[int, int, datetime]] = []
        for start, end in candidates:
            first_ts = group[start].timestamp
            last_ts = group[end - 1].timestamp
            if merged and first_ts <= merged[-1][2] + window:
                prev_start, prev_end, prev_last = merged[-1]
                merged[-1] = (prev_start, max(prev_end, end), max(prev_last, last_ts))
            else:
                merged.append((start, end, last_ts))

        for start, end, _ in merged:
            evidence = tuple(group[start:end])
            windows.append(
                DetectionWindow(
                    username=username,
                    source_ip=source_ip,
                    events=evidence,
                )
            )

    windows.sort(key=lambda item: (item.first_seen, item.username, item.source_ip))
    return windows


def _to_detection_event(event: SecurityEvent) -> DetectionEvent:
    return DetectionEvent(
        event_id=event.event_id,
        timestamp=as_utc(event.timestamp),
        username=event.username or "",
        source_ip=event.source_ip or "",
        event_type=event.event_type,
        action=event.action,
        outcome=event.outcome,
    )


def _alert_row(window: DetectionWindow) -> Alert:
    return Alert(
        id=uuid.uuid4(),
        rule_id=RULE_ID,
        rule_version=RULE_VERSION,
        title=ALERT_TITLE,
        description=(
            f"{len(window.events)} failed authentication attempts for user "
            f"'{window.username}' from {window.source_ip} matched rule "
            f"{RULE_ID} (at least {THRESHOLD} failures in any "
            f"{int(WINDOW.total_seconds() // 60)}-minute window)."
        ),
        severity=ALERT_SEVERITY,
        status="open",
        first_seen_at=window.first_seen,
        last_seen_at=window.last_seen,
        event_count=len(window.events),
        dedup_key=window.dedup_key,
        created_at=utcnow(),
    )


def _insert_alerts(
    session: Session,
    windows: list[DetectionWindow],
    orm_by_id: dict[uuid.UUID, SecurityEvent],
    existing_keys: set[str],
) -> tuple[list[uuid.UUID], int]:
    """Insert every new alert in two statements instead of nine per alert.

    The straightforward loop - add one alert, link its evidence, flush - costs a
    SAVEPOINT, an INSERT, one INSERT per evidence row and a RELEASE per alert.
    At 6000 alerts that measured 25 seconds, nearly all of it round trips.

    The savepoint existed to survive a concurrent run inserting the same dedup
    key. So the batch runs inside one savepoint: on collision the batch is
    rolled back and the per-alert path below redoes it. The rare case keeps the
    original behaviour, the common case gets one round trip per table.
    """
    alerts = [_alert_row(window) for window in windows]
    links = [
        {"alert_id": alert.id, "event_id": event.event_id}
        for alert, window in zip(alerts, windows, strict=True)
        for event in window.events
        if event.event_id in orm_by_id
    ]

    try:
        with session.begin_nested():
            session.add_all(alerts)
            session.flush()
            if links:
                session.execute(insert(alert_events), links)
        for alert in alerts:
            existing_keys.add(alert.dedup_key)
        return [alert.id for alert in alerts], 0
    except IntegrityError:
        # A concurrent detection run won the race for at least one dedup key.
        # Fall back to one alert at a time so the losers are skipped, not lost.
        for alert in alerts:
            if alert in session:
                session.expunge(alert)

    created: list[uuid.UUID] = []
    skipped = 0
    for window in windows:
        alert = _alert_row(window)
        try:
            with session.begin_nested():
                session.add(alert)
                alert.evidence_events = [
                    orm_by_id[event.event_id] for event in window.events
                ]
                session.flush()
            created.append(alert.id)
            existing_keys.add(window.dedup_key)
        except IntegrityError:
            if alert in session:
                session.expunge(alert)
            skipped += 1
    return created, skipped


def run_detection(session: Session, *, commit: bool = True) -> DetectionRunResult:
    """Evaluate all imported authentication failures and persist new alerts."""
    rows = list(
        session.scalars(
            select(SecurityEvent)
            .where(
                SecurityEvent.event_type == AUTH_EVENT_TYPE,
                SecurityEvent.action == AUTH_ACTION,
                SecurityEvent.outcome == "failure",
                SecurityEvent.username.is_not(None),
                SecurityEvent.source_ip.is_not(None),
            )
            .order_by(
                SecurityEvent.timestamp.asc(),
                SecurityEvent.event_id.asc(),
            )
        ).all()
    )

    detection_events = [_to_detection_event(row) for row in rows]
    windows = find_suspicious_login_windows(detection_events)

    orm_by_id = {row.event_id: row for row in rows}
    dedup_keys = [window.dedup_key for window in windows]
    existing_keys: set[str] = set()
    if dedup_keys:
        existing_keys = set(
            session.scalars(
                select(Alert.dedup_key).where(Alert.dedup_key.in_(dedup_keys))
            ).all()
        )

    created_ids: list[uuid.UUID] = []
    skipped_existing = 0

    pending = [window for window in windows if window.dedup_key not in existing_keys]
    skipped_existing += len(windows) - len(pending)

    if pending:
        created_ids, skipped = _insert_alerts(
            session, pending, orm_by_id, existing_keys
        )
        skipped_existing += skipped

    if commit:
        session.commit()
    else:
        session.flush()

    return DetectionRunResult(
        events_scanned=len(rows),
        windows_detected=len(windows),
        alerts_created=len(created_ids),
        alerts_skipped_existing=skipped_existing,
        created_alert_ids=created_ids,
    )
