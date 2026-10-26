"""Deterministic investigation report generation."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sentinelflow.core.time import as_utc
from sentinelflow.models.alert import Alert, alert_events
from sentinelflow.models.security_event import SecurityEvent
from sentinelflow.schemas.alerts import (
    MAX_REPORT_EVIDENCE,
    InvestigationReportResponse,
    ReportEvidence,
    ReportTimelineItem,
    RiskLevel,
)
from sentinelflow.services.detection import RULE_ID, RULE_VERSION, THRESHOLD, WINDOW

#: Identifies which code produced a persisted report body.
GENERATOR = "deterministic"
GENERATOR_VERSION = "1.0.0"

RISK_BY_SEVERITY: dict[str, RiskLevel] = {
    "critical": "critical",
    "high": "high",
    "medium": "medium",
    "low": "low",
    "info": "low",
}

RECOMMENDED_ACTIONS = [
    "Verify whether the source IP is expected for this user (for example VPN, office, or known travel).",
    "Review authentication, VPN, and application logs for the user and affected assets around the alert window.",
    "Check whether any successful login followed the failures and whether the account owner recognizes the activity.",
    "Contact the account owner or identity team to confirm whether the attempts were authorized.",
    "Escalate the alert to a human analyst for review; do not take automated blocking or account-disabling actions.",
]

LIMITATIONS = [
    "This rule detects a pattern of failed authentication attempts; it does not prove that a system was compromised.",
    "The analysis covers only imported event data. Endpoint, network, and identity-provider telemetry are not correlated.",
    "Event timestamps depend on source clocks and may be inaccurate or skewed.",
    "A successful login after the failures may be legitimate or malicious and requires human review.",
    "The deterministic report does not use an LLM or perform any automated response action.",
    "Raw messages are included as evidence and may contain sensitive data; access is limited by API authentication and role-based authorization.",
]


def _timeline_description(event: SecurityEvent) -> str:
    username = event.username or "unknown user"
    source_ip = event.source_ip or "unknown source"
    asset = event.asset_id or "unknown asset"
    return (
        f"{event.action} {event.outcome} for user '{username}' from {source_ip} "
        f"on asset '{asset}'"
    )


def evidence_query(alert_id: uuid.UUID):
    """Base SELECT over one alert's evidence events.

    Public so read-only agent tools can reuse the same scoping instead of
    re-implementing the join.
    """
    return (
        select(SecurityEvent)
        .join(alert_events, alert_events.c.event_id == SecurityEvent.event_id)
        .where(alert_events.c.alert_id == alert_id)
    )


def count_alert_evidence(session: Session, alert_id: uuid.UUID) -> int:
    """Count evidence rows without loading them into memory."""
    subquery = evidence_query(alert_id).subquery()
    return session.scalar(select(func.count()).select_from(subquery)) or 0


def count_alert_failures(session: Session, alert_id: uuid.UUID) -> int:
    """Count linked events whose outcome is a failure.

    The summary must not call every linked event a failed attempt: a rule may
    link a successful login alongside the failures, and the report would then
    describe the evidence wrongly while still looking well formed.
    """
    subquery = evidence_query(alert_id).subquery()
    return (
        session.scalar(
            select(func.count())
            .select_from(subquery)
            .where(subquery.c.outcome == "failure")
        )
        or 0
    )


def load_alert_evidence(
    session: Session,
    alert_id: uuid.UUID,
    *,
    limit: int,
    offset: int,
) -> list[SecurityEvent]:
    """Load one page of evidence in deterministic (timestamp, event_id) order."""
    return list(
        session.scalars(
            evidence_query(alert_id)
            .order_by(
                SecurityEvent.timestamp.asc(),
                SecurityEvent.event_id.asc(),
            )
            .limit(limit)
            .offset(offset)
        ).all()
    )


def to_report_evidence(event: SecurityEvent) -> ReportEvidence:
    return ReportEvidence(
        event_id=event.event_id,
        timestamp=as_utc(event.timestamp),
        event_type=event.event_type,
        username=event.username,
        source_ip=event.source_ip,
        asset_id=event.asset_id,
        action=event.action,
        outcome=event.outcome,
        source=event.source,
        raw_message=event.raw_message,
    )


def build_report(
    session: Session,
    alert_id: uuid.UUID,
    *,
    evidence_limit: int = MAX_REPORT_EVIDENCE,
    evidence_offset: int = 0,
) -> InvestigationReportResponse | None:
    """Build a deterministic report from stored alert and evidence rows.

    The evidence array is capped at ``evidence_limit`` so a merged alert cannot
    produce an unbounded response. ``evidence_total`` always reports the real
    number of linked events, and ``evidence_truncated`` tells the caller whether
    this response is a subset of the full evidence set.
    """
    if evidence_limit < 1:
        raise ValueError("evidence_limit must be at least 1")
    if evidence_offset < 0:
        raise ValueError("evidence_offset must not be negative")

    alert = session.get(Alert, alert_id)
    if alert is None:
        return None

    total = count_alert_evidence(session, alert_id)
    evidence = load_alert_evidence(
        session,
        alert_id,
        limit=evidence_limit,
        offset=evidence_offset,
    )

    # Every row comes from a join against security_events, so identifiers are
    # real by construction. Re-verify anyway: a report is an evidence artifact
    # and must never cite an event that does not exist.
    if evidence:
        evidence_ids = [event.event_id for event in evidence]
        existing_ids = set(
            session.scalars(
                select(SecurityEvent.event_id).where(
                    SecurityEvent.event_id.in_(evidence_ids)
                )
            ).all()
        )
        if set(evidence_ids) != existing_ids:
            raise RuntimeError("Alert references evidence events that do not exist")

    truncated = total > evidence_offset + len(evidence)
    shown = len(evidence)

    failures = count_alert_failures(session, alert_id)

    if evidence:
        username = evidence[0].username or "unknown user"
        source_ip = evidence[0].source_ip or "unknown source"
        # The window belongs to the alert, not to the page being rendered:
        # a truncated or offset response used to state a narrower window than
        # the alert actually covered.
        first_seen = as_utc(alert.first_seen_at)
        last_seen = as_utc(alert.last_seen_at)
        if failures == total:
            counted = f"{total} failed authentication attempts"
        else:
            counted = (
                f"{total} authentication events ({failures} failed) "
            )
        summary = (
            f"Rule {alert.rule_id} identified {counted} "
            f"for user '{username}' from {source_ip} between "
            f"{first_seen.isoformat()} and {last_seen.isoformat()}."
        )
        if truncated:
            summary += (
                f" This response shows {shown} of {total} evidence events "
                f"starting at offset {evidence_offset}."
            )
        reasoning = (
            f"Rule {RULE_ID} (version {RULE_VERSION}) fires when the same username "
            f"and source IP produce at least {THRESHOLD} failed authentication/login "
            f"events within a {int(WINDOW.total_seconds() // 60)}-minute window. "
            f"This alert links {total} evidence events from the database. "
            "The rule sorts events by timestamp, includes both window boundaries, "
            "and groups only events with the same username and source IP. The "
            "deduplication key is derived from the rule and the first evidence "
            "event, so re-running detection on the same data does not create a "
            "duplicate alert."
        )
    else:
        summary = alert.description
        reasoning = (
            f"Rule {RULE_ID} (version {RULE_VERSION}) created this alert, but no "
            "evidence events are currently linked to it. The evidence chain is "
            "incomplete and requires manual review."
        )

    timeline = [
        ReportTimelineItem(
            timestamp=as_utc(event.timestamp),
            event_id=event.event_id,
            description=_timeline_description(event),
        )
        for event in evidence
    ]

    return InvestigationReportResponse(
        alert_id=alert.id,
        summary=summary,
        risk_level=RISK_BY_SEVERITY.get(alert.severity, "high"),
        evidence=[to_report_evidence(event) for event in evidence],
        timeline=timeline,
        reasoning=reasoning,
        recommended_actions=RECOMMENDED_ACTIONS,
        limitations=LIMITATIONS,
        evidence_total=total,
        evidence_truncated=truncated,
    )
