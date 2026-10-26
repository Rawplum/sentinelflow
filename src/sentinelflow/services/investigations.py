"""Investigation orchestration: create a task, run the agent, persist the trace."""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sentinelflow.ai.agent import AGENT_LIMITATIONS, PROMPT_VERSION, run_agent
from sentinelflow.ai.model_client import AgentFindings, ModelClient
from sentinelflow.ai.tools import build_context, to_report_evidence
from sentinelflow.core.config import get_settings
from sentinelflow.core.time import as_utc, utcnow
from sentinelflow.models.alert import Alert
from sentinelflow.models.investigation import (
    Investigation,
    InvestigationRound,
    InvestigationToolCall,
)
from sentinelflow.models.security_event import SecurityEvent
from sentinelflow.models.user import User
from sentinelflow.schemas.alerts import (
    InvestigationReportResponse,
    ReportTimelineItem,
)
from sentinelflow.services.audit import record_audit
from sentinelflow.services.investigation_reports import create_report_version
from sentinelflow.services.reports import count_alert_evidence

#: Error text used when a task is recovered from a dead or hung worker.
STALE_ERROR = "Investigation did not finish (interrupted or timed out)"


class InvestigationConflictError(Exception):
    """Another investigation for the same alert is still running."""


class InvestigationQueueFullError(Exception):
    """Too many investigations are queued or running; refuse new ones."""


def get_investigation(
    session: Session, investigation_id: uuid.UUID
) -> Investigation | None:
    return session.get(Investigation, investigation_id)


def list_tool_calls(
    session: Session, investigation_id: uuid.UUID
) -> list[InvestigationToolCall]:
    return list(
        session.scalars(
            select(InvestigationToolCall)
            .where(InvestigationToolCall.investigation_id == investigation_id)
            .order_by(
                InvestigationToolCall.sequence.asc(),
                InvestigationToolCall.id.asc(),
            )
        ).all()
    )


def list_rounds(
    session: Session, investigation_id: uuid.UUID
) -> list[InvestigationRound]:
    return list(
        session.scalars(
            select(InvestigationRound)
            .where(InvestigationRound.investigation_id == investigation_id)
            .order_by(
                InvestigationRound.round_index.asc(),
                InvestigationRound.id.asc(),
            )
        ).all()
    )


def _build_report_from_findings(
    session: Session,
    alert: Alert,
    findings: AgentFindings,
) -> InvestigationReportResponse:
    """Turn validated findings into a report body backed by real events."""
    cited: list[uuid.UUID] = []
    for event_id in findings.cited_event_ids:
        if event_id not in cited:
            cited.append(event_id)

    events = [
        event
        for event in (session.get(SecurityEvent, event_id) for event_id in cited)
        if event is not None
    ]
    events.sort(key=lambda item: (item.timestamp, str(item.event_id)))

    total = count_alert_evidence(session, alert.id)

    return InvestigationReportResponse(
        alert_id=alert.id,
        summary=findings.summary,
        risk_level=findings.risk_level,
        evidence=[to_report_evidence(event) for event in events],
        timeline=[
            ReportTimelineItem(
                timestamp=event.timestamp,
                event_id=event.event_id,
                description=(
                    f"{event.action} {event.outcome} for user "
                    f"'{event.username or 'unknown user'}' from "
                    f"{event.source_ip or 'unknown source'}"
                ),
            )
            for event in events
        ],
        reasoning=findings.reasoning,
        recommended_actions=findings.recommended_actions,
        limitations=[*findings.limitations, *AGENT_LIMITATIONS],
        evidence_total=total,
        # For agent reports the evidence array is the cited subset of the full
        # evidence set, so it is flagged as a subset rather than a page.
        evidence_truncated=len(events) < total,
    )


def terminate_investigation(
    session: Session,
    investigation: Investigation,
    *,
    status: str,
    error: str | None,
    duration_ms: int | None = None,
    error_code: str | None = None,
) -> Investigation:
    """Move a task to a terminal state. Never leaves it 'running'."""
    now = utcnow()
    investigation.status = status
    investigation.error = error[:500] if error else None
    investigation.error_code = error_code
    investigation.completed_at = now
    investigation.lease_expires_at = None
    investigation.next_attempt_at = None
    if duration_ms is None:
        started = as_utc(investigation.started_at or investigation.created_at)
        duration_ms = max(int((now - started).total_seconds() * 1000), 0)
    investigation.duration_ms = duration_ms
    session.flush()
    return investigation


def find_running_investigation(
    session: Session,
    alert_id: uuid.UUID,
    *,
    stale_after_seconds: int,
) -> Investigation | None:
    """Return a fresh 'running' investigation for this alert, if any.

    Stale rows are ignored so a crashed worker cannot block new runs forever;
    they are recovered separately when they are read.
    """
    cutoff = utcnow() - timedelta(seconds=stale_after_seconds)
    return session.scalars(
        select(Investigation)
        .where(
            Investigation.alert_id == alert_id,
            Investigation.status.in_(("pending", "running")),
            Investigation.created_at >= cutoff,
        )
        .order_by(Investigation.created_at.desc())
    ).first()


def _record_completion(session: Session, investigation: Investigation) -> None:
    """Audit the terminal outcome. Skipped while a retry is pending."""
    if investigation.status in ("pending", "running"):
        return
    record_audit(
        session,
        actor_user_id=investigation.created_by_user_id,
        actor_username=investigation.created_by_username,
        action="investigations.complete",
        outcome="success" if investigation.status == "succeeded" else "failure",
        resource_type="investigation",
        resource_id=str(investigation.id),
        request_id=investigation.request_id,
        details={
            "alert_id": str(investigation.alert_id),
            "status": investigation.status,
            "error_code": investigation.error_code,
            "attempt_count": investigation.attempt_count,
            "rounds_used": investigation.rounds_used,
            "tool_calls_used": investigation.tool_calls_used,
            "duration_ms": investigation.duration_ms,
            "report_id": str(investigation.report_id)
            if investigation.report_id
            else None,
        },
    )


def create_investigation(
    session: Session,
    alert_id: uuid.UUID,
    *,
    user: User,
    client: ModelClient,
    request_id: str | None = None,
) -> Investigation | None:
    """Persist a queued investigation. Returns None when the alert is unknown.

    The row is written before any model call so a crash still leaves a record,
    and so the client can poll it immediately.
    """
    alert = session.get(Alert, alert_id)
    if alert is None:
        return None

    # Bound the queue itself: an authenticated caller must not be able to
    # enqueue unbounded work (each task can burn model budget).
    settings = get_settings()
    cutoff = utcnow() - timedelta(seconds=settings.agent_stale_after_seconds)
    queued = session.scalar(
        select(func.count())
        .select_from(Investigation)
        .where(
            Investigation.status.in_(("pending", "running")),
            Investigation.created_at >= cutoff,
        )
    )
    if (queued or 0) >= settings.agent_max_pending:
        raise InvestigationQueueFullError(
            f"Queue is full ({queued} investigations pending or running)"
        )

    # Guard against double submits and retry storms: one live investigation per
    # alert. This is enforced server-side, not by disabling a button.
    running = find_running_investigation(
        session,
        alert_id,
        stale_after_seconds=settings.agent_stale_after_seconds,
    )
    if running is not None:
        raise InvestigationConflictError(
            f"Investigation {running.id} is already running for this alert"
        )

    investigation = Investigation(
        alert_id=alert.id,
        status="pending",
        model_provider=client.provider,
        model_name=client.model,
        prompt_version=PROMPT_VERSION,
        rounds_used=0,
        tool_calls_used=0,
        request_id=request_id,
        attempt_count=0,
        max_attempts=get_settings().agent_max_attempts,
        created_by_user_id=user.id,
        created_by_username=user.username,
    )
    session.add(investigation)
    session.flush()
    return investigation


def execute_investigation(
    session: Session,
    investigation_id: uuid.UUID,
    *,
    client: ModelClient,
    max_rounds: int,
    max_tool_calls: int,
    tool_timeout_seconds: float,
    commit: bool = True,
    retry_transient: bool = False,
) -> Investigation | None:
    """Run a claimed investigation and persist its trace.

    Idempotent: a task that is not in ``running`` state is returned untouched,
    so a duplicate dispatch cannot run the same task twice.

    ``retry_transient`` is set by the queue worker: a retryable provider failure
    returns the task to ``pending`` (bounded by ``max_attempts``) instead of
    failing it outright. The CLI passes False so a single run is a single run.
    """
    investigation = session.get(Investigation, investigation_id)
    if investigation is None:
        return None
    if investigation.status != "running":
        return investigation

    alert = session.get(Alert, investigation.alert_id)
    user = (
        session.get(User, investigation.created_by_user_id)
        if investigation.created_by_user_id is not None
        else None
    )
    if alert is None or user is None:
        terminate_investigation(
            session,
            investigation,
            status="failed",
            error="Investigation context is no longer available",
            error_code="context_missing",
        )
        _record_completion(session, investigation)
        if commit:
            session.commit()
        return investigation

    context = build_context(session, alert, user)

    try:
        result = run_agent(
            client=client,
            context=context,
            max_rounds=max_rounds,
            max_tool_calls=max_tool_calls,
            tool_timeout_seconds=tool_timeout_seconds,
            max_runtime_seconds=get_settings().agent_max_runtime_seconds,
        )
    except Exception as exc:  # noqa: BLE001 - a crash must still terminate the task
        # Never leak the message: it may contain provider details.
        terminate_investigation(
            session,
            investigation,
            status="failed",
            error=f"{exc.__class__.__name__}: investigation aborted",
            error_code="crashed",
        )
        _record_completion(session, investigation)
        if commit:
            session.commit()
        return investigation

    for record in result.rounds:
        session.add(
            InvestigationRound(
                investigation_id=investigation.id,
                round_index=record.round_index,
                attempt_index=investigation.attempt_count,
                latency_ms=record.latency_ms,
                outcome=record.outcome,
                tool_call_count=record.tool_call_count,
                error=record.error,
            )
        )

    for record in result.tool_calls:
        session.add(
            InvestigationToolCall(
                investigation_id=investigation.id,
                sequence=record.sequence,
                attempt_index=investigation.attempt_count,
                tool_name=record.tool_name,
                arguments=record.arguments,
                status=record.status,
                result_summary=record.result_summary,
                error=record.error,
                duration_ms=record.duration_ms,
            )
        )

    investigation.rounds_used = result.rounds_used
    investigation.tool_calls_used = result.tool_calls_used

    if (
        result.status == "succeeded"
        and result.findings is not None
        # A retry reuses the same row; never create a second report version.
        and investigation.report_id is None
    ):
        content = _build_report_from_findings(session, alert, result.findings)
        report = create_report_version(
            session,
            alert.id,
            user=user,
            generator="agent",
            generator_version=PROMPT_VERSION,
            content=content,
            commit=False,
        )
        if report is not None:
            investigation.report_id = report.id

    if (
        result.status == "failed"
        and retry_transient
        and result.retryable
        and investigation.attempt_count < investigation.max_attempts
    ):
        settings = get_settings()
        investigation.status = "pending"
        investigation.next_attempt_at = utcnow() + timedelta(
            seconds=settings.agent_retry_backoff_seconds
        )
        investigation.lease_expires_at = None
        investigation.error = result.error[:500] if result.error else None
        investigation.error_code = result.error_code or "model_transient"
        session.flush()
        if commit:
            session.commit()
        return investigation

    terminate_investigation(
        session,
        investigation,
        status=result.status,
        error=result.error,
        duration_ms=result.duration_ms,
        error_code=result.error_code,
    )
    _record_completion(session, investigation)

    if commit:
        session.commit()
    return investigation


def recover_stale_investigation(
    session: Session,
    investigation: Investigation,
    *,
    stale_after_seconds: int,
) -> bool:
    """Terminate a task that has been 'running' far longer than any run may take.

    This is the safety net for a worker that died mid-run (process restart, OOM,
    killed container). Without it the row would stay 'running' forever and the
    UI would poll indefinitely. Returns True when the row was changed.
    """
    if investigation.status != "running":
        return False

    now = utcnow()
    if investigation.lease_expires_at is not None:
        # A worker holds a lease; only an expired lease means it died.
        if as_utc(investigation.lease_expires_at) >= now:
            return False
    else:
        started = as_utc(investigation.started_at or investigation.created_at)
        if now - started < timedelta(seconds=stale_after_seconds):
            return False

    terminate_investigation(
        session,
        investigation,
        status="failed",
        error=STALE_ERROR,
        error_code="interrupted",
    )
    session.commit()
    return True


def run_investigation(
    session: Session,
    alert_id: uuid.UUID,
    *,
    user: User,
    client: ModelClient,
    max_rounds: int,
    max_tool_calls: int,
    tool_timeout_seconds: float,
    request_id: str | None = None,
    commit: bool = False,
) -> Investigation | None:
    """Create and execute in one call. Used by the CLI, evals and unit tests."""
    investigation = create_investigation(
        session,
        alert_id,
        user=user,
        client=client,
        request_id=request_id,
    )
    if investigation is None:
        return None

    return execute_investigation(
        session,
        investigation.id,
        client=client,
        max_rounds=max_rounds,
        max_tool_calls=max_tool_calls,
        tool_timeout_seconds=tool_timeout_seconds,
        commit=commit,
    )
