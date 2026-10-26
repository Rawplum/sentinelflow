"""Agent investigation request and response schemas."""

import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from sentinelflow.schemas.common import UTCDateTime

InvestigationStatus = Literal[
    "pending", "running", "succeeded", "failed", "limit_reached"
]
ToolCallStatus = Literal["ok", "error", "timeout", "denied", "invalid"]
RoundOutcome = Literal["tool_calls", "findings", "error", "budget_exhausted"]


class InvestigationRoundRead(BaseModel):
    """One model turn. Contains no prompt or model-response text."""

    model_config = ConfigDict(from_attributes=True)

    round_index: int
    attempt_index: int = 1
    latency_ms: int
    outcome: RoundOutcome
    tool_call_count: int
    error: str | None
    created_at: UTCDateTime


class InvestigationToolCallRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sequence: int
    attempt_index: int = 1
    tool_name: str
    arguments: dict[str, Any]
    status: ToolCallStatus
    result_summary: dict[str, Any] | None
    error: str | None
    duration_ms: int
    created_at: UTCDateTime


class InvestigationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    alert_id: uuid.UUID
    status: InvestigationStatus
    model_provider: str | None
    model_name: str | None
    prompt_version: str
    rounds_used: int
    tool_calls_used: int
    error: str | None
    #: Machine-readable failure reason (model_timeout, citation_invalid, ...).
    error_code: str | None = None
    #: How many times a worker claimed this task, and the cap.
    attempt_count: int = 0
    max_attempts: int = 1
    request_id: str | None
    duration_ms: int | None
    report_id: uuid.UUID | None
    created_by_username: str | None
    created_at: UTCDateTime
    started_at: UTCDateTime | None = None
    completed_at: UTCDateTime | None
    rounds: list[InvestigationRoundRead] = []
    tool_calls: list[InvestigationToolCallRead] = []
