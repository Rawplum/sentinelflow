"""Alert, status transition, evidence and investigation report schemas."""

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from sentinelflow.schemas.common import UTCDateTime

RiskLevel = Literal["low", "medium", "high", "critical"]
AlertStatus = Literal["open", "acknowledged", "investigating", "closed"]
ReportStatus = Literal["draft", "finalized", "superseded"]
ReportGenerator = Literal["deterministic", "agent"]

#: Hard cap on how many evidence rows a single report may embed.
MAX_REPORT_EVIDENCE = 100
#: Default page size for the dedicated evidence endpoint.
DEFAULT_EVIDENCE_PAGE_SIZE = 50
#: Hard cap on the dedicated evidence endpoint page size.
MAX_EVIDENCE_PAGE_SIZE = 200


class AlertRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    rule_id: str
    rule_version: str
    title: str
    description: str
    severity: str
    status: str
    first_seen_at: UTCDateTime
    last_seen_at: UTCDateTime
    event_count: int
    created_at: UTCDateTime
    evidence_count: int = 0


class AlertListResponse(BaseModel):
    items: list[AlertRead]
    total: int
    limit: int
    offset: int


class AlertStatusHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    from_status: str | None
    to_status: str
    changed_by_username: str | None
    reason: str | None
    created_at: UTCDateTime


class AlertDetail(AlertRead):
    """Alert with its status history.

    This is the authoritative source for alert metadata so clients no longer
    have to carry alert state through client-side routing.
    """

    status_history: list[AlertStatusHistoryRead] = Field(default_factory=list)


class AlertStatusUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: AlertStatus
    reason: str | None = Field(default=None, max_length=500)


class ReportEvidence(BaseModel):
    event_id: uuid.UUID
    timestamp: UTCDateTime
    event_type: str
    username: str | None
    source_ip: str | None
    asset_id: str | None
    action: str
    outcome: str
    source: str
    raw_message: str | None = None


class ReportTimelineItem(BaseModel):
    timestamp: UTCDateTime
    event_id: uuid.UUID
    description: str


class InvestigationReportResponse(BaseModel):
    """Deterministic or agent-generated report body.

    ``evidence`` may be a page of the full evidence set; ``evidence_total`` and
    ``evidence_truncated`` describe the complete set so a client can tell the
    difference between "there are 5 events" and "5 of 600 are shown".
    """

    alert_id: uuid.UUID
    summary: str
    risk_level: RiskLevel
    evidence: list[ReportEvidence]
    timeline: list[ReportTimelineItem]
    reasoning: str
    recommended_actions: list[str] = Field(min_length=1)
    limitations: list[str] = Field(min_length=1)
    evidence_total: int = 0
    evidence_truncated: bool = False


class AlertEvidenceListResponse(BaseModel):
    items: list[ReportEvidence]
    total: int
    limit: int
    offset: int


class InvestigationReportRead(BaseModel):
    """A persisted report version, including its snapshot provenance."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    alert_id: uuid.UUID
    version: int
    status: ReportStatus
    generator: ReportGenerator
    generator_version: str
    evidence_count: int
    evidence_truncated: bool
    created_by_username: str | None
    created_at: UTCDateTime
    finalized_at: UTCDateTime | None
    finalized_by_username: str | None
    content: InvestigationReportResponse


class InvestigationReportListResponse(BaseModel):
    items: list[InvestigationReportRead]
    total: int


class ReportCreateRequest(BaseModel):
    """Body for creating a new report version.

    ``generator`` is constrained to the deterministic generator for now; the
    agent generator is written by the investigation workflow, not by clients.
    """

    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=500)
