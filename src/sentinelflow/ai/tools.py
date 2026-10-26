"""Whitelisted, read-only tools available to the investigation agent.

Design rules enforced here, not in the prompt:

- Only tools registered in ``TOOL_SPECS`` can run. An unknown name is rejected
  before any model-supplied argument is touched.
- Every tool declares a Pydantic input model with ``extra="forbid"``.
- Every tool declares the backend permission it needs; the caller's role is
  checked with the same ``has_permission`` used by the HTTP layer.
- Every query is scoped to the investigation's alert. There is no tool that can
  reach another alert, run SQL, touch the filesystem, or open a network socket.
- All tools are read-only. No tool writes, blocks, deletes, or scans.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from sentinelflow.core.permissions import Permission, has_permission
from sentinelflow.models.alert import Alert
from sentinelflow.models.security_event import SecurityEvent
from sentinelflow.models.user import User
from sentinelflow.services.alerts import get_status_history
from sentinelflow.services.reports import (
    count_alert_evidence,
    evidence_query,
    load_alert_evidence,
    to_report_evidence,
)

RUNBOOK_PATH = Path(__file__).resolve().parents[3] / "data" / "runbooks.json"
MAX_RAW_MESSAGE_CHARS = 500


class GetAlertDetailsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GetRelatedEventsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # strict: reject "5" or true instead of coercing them to 5 / 1.
    limit: int = Field(default=10, ge=1, le=50, strict=True)
    offset: int = Field(default=0, ge=0, strict=True)


class SearchEventsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keyword: str | None = Field(default=None, min_length=1, max_length=100)
    outcome: Literal["success", "failure", "unknown"] | None = None
    action: str | None = Field(default=None, min_length=1, max_length=100)
    limit: int = Field(default=10, ge=1, le=50, strict=True)


class SearchRunbooksInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=100)
    limit: int = Field(default=3, ge=1, le=5, strict=True)


@dataclass(frozen=True)
class ToolContext:
    """Everything a tool is allowed to see. Note: no session factory, no engine."""

    session: Session
    alert: Alert
    user: User
    evidence_ids: frozenset[uuid.UUID]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]
    required_permission: Permission
    handler: Callable[[ToolContext, Any], dict[str, Any]]


def _truncate(value: str | None) -> str | None:
    if value is None:
        return None
    if len(value) <= MAX_RAW_MESSAGE_CHARS:
        return value
    return value[:MAX_RAW_MESSAGE_CHARS] + "…[truncated]"


def _get_alert_details(ctx: ToolContext, _: GetAlertDetailsInput) -> dict[str, Any]:
    alert = ctx.alert
    history = get_status_history(ctx.session, alert.id)
    return {
        "alert_id": str(alert.id),
        "rule_id": alert.rule_id,
        "rule_version": alert.rule_version,
        "title": alert.title,
        "description": alert.description,
        "severity": alert.severity,
        "status": alert.status,
        "first_seen_at": alert.first_seen_at.isoformat(),
        "last_seen_at": alert.last_seen_at.isoformat(),
        "event_count": alert.event_count,
        "evidence_total": count_alert_evidence(ctx.session, alert.id),
        "status_history": [
            {
                "from_status": item.from_status,
                "to_status": item.to_status,
                "changed_by_username": item.changed_by_username,
                "reason": item.reason,
                "created_at": item.created_at.isoformat(),
            }
            for item in history
        ],
    }


def _get_related_events(
    ctx: ToolContext, params: GetRelatedEventsInput
) -> dict[str, Any]:
    rows = load_alert_evidence(
        ctx.session, ctx.alert.id, limit=params.limit, offset=params.offset
    )
    total = count_alert_evidence(ctx.session, ctx.alert.id)
    return {
        "total": total,
        "offset": params.offset,
        "returned": len(rows),
        "events": [
            {
                "event_id": str(item.event_id),
                "timestamp": item.timestamp.isoformat(),
                "event_type": item.event_type,
                "username": item.username,
                "source_ip": item.source_ip,
                "asset_id": item.asset_id,
                "action": item.action,
                "outcome": item.outcome,
                "source": item.source,
                "raw_message": _truncate(item.raw_message),
            }
            for item in rows
        ],
    }


def _search_events(ctx: ToolContext, params: SearchEventsInput) -> dict[str, Any]:
    statement = evidence_query(ctx.alert.id)
    if params.keyword:
        escaped = (
            params.keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        statement = statement.where(
            SecurityEvent.raw_message.ilike(f"%{escaped}%", escape="\\")
        )
    if params.outcome:
        statement = statement.where(SecurityEvent.outcome == params.outcome)
    if params.action:
        statement = statement.where(SecurityEvent.action == params.action)

    rows = list(
        ctx.session.scalars(
            statement.order_by(
                SecurityEvent.timestamp.asc(), SecurityEvent.event_id.asc()
            ).limit(params.limit)
        ).all()
    )
    return {
        "returned": len(rows),
        "events": [
            {
                "event_id": str(item.event_id),
                "timestamp": item.timestamp.isoformat(),
                "username": item.username,
                "source_ip": item.source_ip,
                "action": item.action,
                "outcome": item.outcome,
                "raw_message": _truncate(item.raw_message),
            }
            for item in rows
        ],
    }


@lru_cache(maxsize=1)
def _load_runbooks() -> tuple[dict[str, Any], ...]:
    try:
        raw = json.loads(RUNBOOK_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    return tuple(raw) if isinstance(raw, list) else ()


def _search_runbooks(ctx: ToolContext, params: SearchRunbooksInput) -> dict[str, Any]:
    needle = params.query.strip().lower()
    matches: list[dict[str, Any]] = []
    for entry in _load_runbooks():
        haystack = " ".join(
            [
                str(entry.get("title", "")),
                str(entry.get("summary", "")),
                " ".join(entry.get("tags", []) or []),
                " ".join(entry.get("steps", []) or []),
            ]
        ).lower()
        if needle in haystack:
            matches.append(
                {
                    "id": entry.get("id"),
                    "title": entry.get("title"),
                    "summary": entry.get("summary"),
                    "steps": entry.get("steps", [])[:6],
                }
            )
        if len(matches) >= params.limit:
            break
    return {"returned": len(matches), "runbooks": matches}


TOOL_SPECS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in (
        ToolSpec(
            name="get_alert_details",
            description=(
                "Return the alert under investigation: rule, severity, status, "
                "time window, evidence totals and status history."
            ),
            input_model=GetAlertDetailsInput,
            required_permission=Permission.ALERTS_READ,
            handler=_get_alert_details,
        ),
        ToolSpec(
            name="get_related_events",
            description=(
                "Page through the evidence events linked to this alert. "
                "Ordered by timestamp."
            ),
            input_model=GetRelatedEventsInput,
            required_permission=Permission.ALERTS_READ,
            handler=_get_related_events,
        ),
        ToolSpec(
            name="search_events",
            description=(
                "Search within this alert's evidence only, by keyword in the raw "
                "message, outcome, or action."
            ),
            input_model=SearchEventsInput,
            required_permission=Permission.ALERTS_READ,
            handler=_search_events,
        ),
        ToolSpec(
            name="search_runbooks",
            description=(
                "Search the local, offline runbook corpus for triage guidance."
            ),
            input_model=SearchRunbooksInput,
            required_permission=Permission.REPORTS_READ,
            handler=_search_runbooks,
        ),
    )
}


def tool_definitions() -> list[dict[str, Any]]:
    """OpenAI-style tool schema for the configured model."""
    return [
        {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.input_model.model_json_schema(),
            },
        }
        for spec in TOOL_SPECS.values()
    ]


@dataclass(frozen=True)
class ToolExecution:
    status: str
    result: dict[str, Any] | None
    error: str | None
    duration_ms: int


def execute_tool(
    *,
    name: str,
    arguments: dict[str, Any],
    context: ToolContext,
    timeout_seconds: float,
) -> ToolExecution:
    """Validate, authorize and run one tool call.

    Unknown tools are rejected before their arguments are inspected. Permission
    is checked against the caller's database role, not against anything the
    model produced.
    """
    started = time.monotonic()

    def _elapsed_ms() -> int:
        return int((time.monotonic() - started) * 1000)

    spec = TOOL_SPECS.get(name)
    if spec is None:
        return ToolExecution(
            status="denied",
            result=None,
            error=f"Unknown tool: {name}",
            duration_ms=_elapsed_ms(),
        )

    if not has_permission(context.user.role, spec.required_permission):
        return ToolExecution(
            status="denied",
            result=None,
            error="Caller lacks permission for this tool",
            duration_ms=_elapsed_ms(),
        )

    try:
        params = spec.input_model.model_validate(arguments)
    except ValidationError as exc:
        return ToolExecution(
            status="invalid",
            result=None,
            error=f"Invalid arguments: {exc.error_count()} problem(s)",
            duration_ms=_elapsed_ms(),
        )

    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(spec.handler, context, params)
    try:
        result = future.result(timeout=timeout_seconds)
    except FutureTimeout:
        # The worker thread cannot be killed from here; it is left to finish on
        # its own. Every handler is a bounded read-only query, so the orphaned
        # work cannot mutate state.
        return ToolExecution(
            status="timeout",
            result=None,
            error=f"Tool exceeded {timeout_seconds}s timeout",
            duration_ms=_elapsed_ms(),
        )
    except Exception as exc:
        return ToolExecution(
            status="error",
            result=None,
            error=f"{exc.__class__.__name__}: tool execution failed",
            duration_ms=_elapsed_ms(),
        )
    finally:
        executor.shutdown(wait=False)

    return ToolExecution(
        status="ok",
        result=result,
        error=None,
        duration_ms=_elapsed_ms(),
    )


def summarize_result(result: dict[str, Any] | None) -> dict[str, Any] | None:
    """Build a small, non-sensitive summary for the persisted call log.

    Raw messages are deliberately excluded: the audit trail records what was
    queried and how much came back, not the log content itself.
    """
    if result is None:
        return None
    summary: dict[str, Any] = {}
    for key in ("returned", "total", "offset", "alert_id"):
        if key in result:
            summary[key] = result[key]
    if "events" in result and isinstance(result["events"], list):
        summary["event_ids"] = [item.get("event_id") for item in result["events"][:50]]
    if "runbooks" in result and isinstance(result["runbooks"], list):
        summary["runbook_ids"] = [item.get("id") for item in result["runbooks"]]
    return summary


def evidence_event_ids(session: Session, alert_id: uuid.UUID) -> frozenset[uuid.UUID]:
    return frozenset(
        event.event_id
        for event in load_alert_evidence(session, alert_id, limit=10_000, offset=0)
    )


def build_context(session: Session, alert: Alert, user: User) -> ToolContext:
    return ToolContext(
        session=session,
        alert=alert,
        user=user,
        evidence_ids=evidence_event_ids(session, alert.id),
    )


__all__ = [
    "TOOL_SPECS",
    "ToolContext",
    "ToolExecution",
    "build_context",
    "execute_tool",
    "summarize_result",
    "to_report_evidence",
    "tool_definitions",
]
