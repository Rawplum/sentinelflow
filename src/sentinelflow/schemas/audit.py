"""Audit log response schemas."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict

from sentinelflow.schemas.common import UTCDateTime

AuditOutcome = Literal["success", "failure", "denied"]


class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    actor_user_id: uuid.UUID | None
    actor_username: str | None
    action: str
    resource_type: str | None
    resource_id: str | None
    outcome: AuditOutcome
    source_ip: str | None
    request_id: str | None
    details: dict | None
    created_at: UTCDateTime


class AuditLogListResponse(BaseModel):
    items: list[AuditLogRead]
    total: int
    limit: int
    offset: int
