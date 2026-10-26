"""Security event request and response schemas."""

import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    IPvAnyAddress,
    field_validator,
)

from sentinelflow.schemas.common import UTCDateTime

Outcome = Literal["success", "failure", "unknown"]


class SecurityEventCreate(BaseModel):
    """A single validated event accepted by the import endpoint."""

    model_config = ConfigDict(extra="forbid")

    event_id: uuid.UUID
    timestamp: AwareDatetime
    event_type: str = Field(min_length=1, max_length=100)
    username: str | None = Field(default=None, max_length=255)
    source_ip: IPvAnyAddress | None = None
    asset_id: str | None = Field(default=None, max_length=255)
    action: str = Field(min_length=1, max_length=100)
    outcome: Outcome
    raw_message: str = Field(min_length=1, max_length=8192)
    source: str = Field(min_length=1, max_length=64)

    @field_validator("timestamp")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        return value.astimezone(timezone.utc)


class EventImportRequest(BaseModel):
    """Bounded batch import request."""

    model_config = ConfigDict(extra="forbid")

    events: list[SecurityEventCreate] = Field(min_length=1, max_length=500)


class EventImportResponse(BaseModel):
    received: int
    imported: int
    skipped: int
    skipped_event_ids: list[uuid.UUID]


class SecurityEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: uuid.UUID
    timestamp: UTCDateTime
    event_type: str
    username: str | None
    source_ip: str | None
    asset_id: str | None
    action: str
    outcome: Outcome
    # Null when the caller opted out of raw payloads via include_raw_message=false.
    raw_message: str | None = None
    source: str
    created_at: UTCDateTime


class EventListResponse(BaseModel):
    items: list[SecurityEventRead]
    total: int
    limit: int
    offset: int
