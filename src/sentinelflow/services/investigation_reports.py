"""Persisted investigation report versions.

Reports are stored as a rendered ``content`` body plus an ``input_snapshot`` of
the alert fields and evidence identifiers they were derived from. The snapshot
is deliberately frozen: it records what the report was based on at creation
time, and may legitimately differ from the current database rows later.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sentinelflow.core.time import utcnow
from sentinelflow.models.alert import Alert
from sentinelflow.models.investigation_report import InvestigationReport
from sentinelflow.models.user import User
from sentinelflow.schemas.alerts import MAX_REPORT_EVIDENCE, InvestigationReportResponse
from sentinelflow.services.reports import GENERATOR, GENERATOR_VERSION, build_report


class ReportConflictError(Exception):
    """The requested report operation is not valid for the current state."""


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def build_input_snapshot(
    alert: Alert, report: InvestigationReportResponse
) -> dict:
    """Capture the inputs a report version was generated from."""
    return {
        "captured_at": _iso(utcnow()),
        "alert": {
            "id": str(alert.id),
            "rule_id": alert.rule_id,
            "rule_version": alert.rule_version,
            "title": alert.title,
            "severity": alert.severity,
            "status": alert.status,
            "first_seen_at": _iso(alert.first_seen_at),
            "last_seen_at": _iso(alert.last_seen_at),
            "event_count": alert.event_count,
            "created_at": _iso(alert.created_at),
        },
        "evidence_ids": [str(item.event_id) for item in report.evidence],
        "evidence_total": report.evidence_total,
        "evidence_truncated": report.evidence_truncated,
    }


def next_version(session: Session, alert_id: uuid.UUID) -> int:
    current = session.scalar(
        select(func.max(InvestigationReport.version)).where(
            InvestigationReport.alert_id == alert_id
        )
    )
    return (current or 0) + 1


def get_report(
    session: Session, report_id: uuid.UUID
) -> InvestigationReport | None:
    return session.get(InvestigationReport, report_id)


def list_report_versions(
    session: Session, alert_id: uuid.UUID
) -> list[InvestigationReport]:
    return list(
        session.scalars(
            select(InvestigationReport)
            .where(InvestigationReport.alert_id == alert_id)
            .order_by(
                InvestigationReport.version.desc(),
                InvestigationReport.id.asc(),
            )
        ).all()
    )


def create_report_version(
    session: Session,
    alert_id: uuid.UUID,
    *,
    user: User,
    generator: str = GENERATOR,
    generator_version: str = GENERATOR_VERSION,
    content: InvestigationReportResponse | None = None,
    commit: bool = False,
) -> InvestigationReport | None:
    """Create the next draft version for an alert.

    Returns ``None`` when the alert does not exist. Raises
    :class:`ReportConflictError` when a concurrent writer took the version.
    """
    alert = session.get(Alert, alert_id)
    if alert is None:
        return None

    if content is None:
        content = build_report(
            session,
            alert_id,
            evidence_limit=MAX_REPORT_EVIDENCE,
            evidence_offset=0,
        )
        if content is None:
            return None

    version = next_version(session, alert_id)
    report = InvestigationReport(
        alert_id=alert_id,
        version=version,
        status="draft",
        generator=generator,
        generator_version=generator_version,
        input_snapshot=build_input_snapshot(alert, content),
        content=content.model_dump(mode="json"),
        evidence_count=content.evidence_total,
        evidence_truncated=content.evidence_truncated,
        created_by_user_id=user.id,
        created_by_username=user.username,
    )
    session.add(report)
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError as exc:
        raise ReportConflictError(
            "Another report version was created concurrently; retry"
        ) from exc

    if commit:
        session.commit()
    return report


def finalize_report(
    session: Session,
    report_id: uuid.UUID,
    *,
    user: User,
    commit: bool = False,
) -> InvestigationReport | None:
    """Finalize a draft and supersede any previously finalized version.

    Returns ``None`` when the report does not exist. Raises
    :class:`ReportConflictError` when the report is not a draft, because a
    finalized report must never be edited in place — a revision is a new version.
    """
    report = session.get(InvestigationReport, report_id)
    if report is None:
        return None
    if report.status == "finalized":
        raise ReportConflictError("Report is already finalized")
    if report.status == "superseded":
        raise ReportConflictError("Superseded reports cannot be finalized")

    previous = list(
        session.scalars(
            select(InvestigationReport).where(
                InvestigationReport.alert_id == report.alert_id,
                InvestigationReport.status == "finalized",
                InvestigationReport.id != report.id,
            )
        ).all()
    )
    for item in previous:
        item.status = "superseded"

    report.status = "finalized"
    report.finalized_at = utcnow()
    report.finalized_by_user_id = user.id
    report.finalized_by_username = user.username

    session.flush()
    if commit:
        session.commit()
    return report
