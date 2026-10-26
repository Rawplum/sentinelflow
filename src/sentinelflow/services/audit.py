"""Audit log recording and querying."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sentinelflow.models.audit_log import AuditLog


def record_audit(
    session: Session,
    *,
    actor_user_id: uuid.UUID | None,
    actor_username: str | None,
    action: str,
    outcome: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    source_ip: str | None = None,
    request_id: str | None = None,
    details: dict | None = None,
) -> AuditLog:
    """Add an audit entry to the current transaction (caller commits)."""
    entry = AuditLog(
        actor_user_id=actor_user_id,
        actor_username=actor_username,
        action=action,
        outcome=outcome,
        resource_type=resource_type,
        resource_id=resource_id,
        source_ip=source_ip,
        request_id=request_id,
        details=details,
    )
    session.add(entry)
    return entry


def list_audit_logs(
    session: Session,
    *,
    limit: int,
    offset: int,
    action: str | None = None,
) -> tuple[list[AuditLog], int]:
    conditions = []
    if action is not None:
        conditions.append(AuditLog.action == action)

    count_statement = select(func.count()).select_from(AuditLog)
    statement = select(AuditLog)
    if conditions:
        count_statement = count_statement.where(*conditions)
        statement = statement.where(*conditions)

    total = session.scalar(count_statement) or 0
    items = list(
        session.scalars(
            statement.order_by(
                AuditLog.created_at.desc(),
                AuditLog.id.asc(),
            )
            .limit(limit)
            .offset(offset)
        ).all()
    )
    return items, total
