"""Alert query, detail and status-transition services."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sentinelflow.core.time import utcnow
from sentinelflow.models.alert import Alert, alert_events
from sentinelflow.models.alert_status_history import AlertStatusHistory
from sentinelflow.models.user import User
from sentinelflow.schemas.alerts import AlertRead

#: Legal forward transitions plus an explicit, justified reopen.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "open": frozenset({"acknowledged", "investigating", "closed"}),
    "acknowledged": frozenset({"investigating", "closed"}),
    "investigating": frozenset({"closed"}),
    "closed": frozenset({"open"}),
}

#: Reopening a closed incident requires a written justification.
REASON_REQUIRED_TRANSITIONS: frozenset[tuple[str, str]] = frozenset({("closed", "open")})


class InvalidStatusTransitionError(Exception):
    """A requested status change is not allowed by the transition rules."""

    def __init__(self, from_status: str, to_status: str) -> None:
        super().__init__(
            f"Illegal status transition from '{from_status}' to '{to_status}'"
        )
        self.from_status = from_status
        self.to_status = to_status


class MissingTransitionReasonError(Exception):
    """A transition that requires a reason was requested without one."""

    def __init__(self, from_status: str, to_status: str) -> None:
        super().__init__(
            f"A reason is required for the transition from '{from_status}' "
            f"to '{to_status}'"
        )


def _evidence_count_subquery():
    return (
        select(func.count(alert_events.c.event_id))
        .where(alert_events.c.alert_id == Alert.id)
        .correlate(Alert)
        .scalar_subquery()
    )


def to_alert_read(alert: Alert, evidence_count: int) -> AlertRead:
    return AlertRead.model_validate(alert).model_copy(
        update={"evidence_count": evidence_count}
    )


def list_alerts(
    session: Session, *, limit: int, offset: int
) -> tuple[list[AlertRead], int]:
    """List alerts with evidence counts computed in SQL.

    Counting in SQL avoids loading every evidence row of every alert just to
    report ``evidence_count``.
    """
    total = session.scalar(select(func.count()).select_from(Alert)) or 0
    rows = session.execute(
        select(Alert, _evidence_count_subquery().label("evidence_count"))
        .order_by(Alert.created_at.desc(), Alert.id.asc())
        .limit(limit)
        .offset(offset)
    ).all()
    return [
        to_alert_read(alert, int(evidence_count or 0))
        for alert, evidence_count in rows
    ], total


def get_alert(session: Session, alert_id: uuid.UUID) -> Alert | None:
    return session.get(Alert, alert_id)


def get_alert_read(session: Session, alert_id: uuid.UUID) -> AlertRead | None:
    row = session.execute(
        select(Alert, _evidence_count_subquery().label("evidence_count")).where(
            Alert.id == alert_id
        )
    ).first()
    if row is None:
        return None
    alert, evidence_count = row
    return to_alert_read(alert, int(evidence_count or 0))


def get_status_history(
    session: Session, alert_id: uuid.UUID
) -> list[AlertStatusHistory]:
    return list(
        session.scalars(
            select(AlertStatusHistory)
            .where(AlertStatusHistory.alert_id == alert_id)
            .order_by(
                AlertStatusHistory.created_at.asc(),
                AlertStatusHistory.id.asc(),
            )
        ).all()
    )


def is_transition_allowed(from_status: str, to_status: str) -> bool:
    return to_status in ALLOWED_TRANSITIONS.get(from_status, frozenset())


@dataclass(frozen=True)
class StatusChangeResult:
    alert: Alert
    from_status: str
    to_status: str
    changed: bool


def change_status(
    session: Session,
    alert_id: uuid.UUID,
    *,
    to_status: str,
    user: User,
    reason: str | None = None,
    commit: bool = False,
) -> StatusChangeResult | None:
    """Apply a validated status change and append history.

    Returns ``None`` when the alert does not exist. A same-status request is a
    no-op: the alert is returned with ``changed=False`` and no history row is
    written, which keeps client retries from producing duplicate audit noise.
    """
    alert = session.get(Alert, alert_id)
    if alert is None:
        return None

    from_status = alert.status
    if from_status == to_status:
        return StatusChangeResult(
            alert=alert,
            from_status=from_status,
            to_status=to_status,
            changed=False,
        )

    if not is_transition_allowed(from_status, to_status):
        raise InvalidStatusTransitionError(from_status, to_status)

    if (from_status, to_status) in REASON_REQUIRED_TRANSITIONS and not (
        reason and reason.strip()
    ):
        raise MissingTransitionReasonError(from_status, to_status)

    alert.status = to_status
    session.add(
        AlertStatusHistory(
            alert_id=alert.id,
            from_status=from_status,
            to_status=to_status,
            changed_by_user_id=user.id,
            changed_by_username=user.username,
            reason=reason.strip() if reason else None,
            created_at=utcnow(),
        )
    )
    session.flush()
    if commit:
        session.commit()
    return StatusChangeResult(
        alert=alert,
        from_status=from_status,
        to_status=to_status,
        changed=True,
    )
