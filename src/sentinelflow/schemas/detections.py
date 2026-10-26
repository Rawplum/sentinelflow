"""Detection request and response schemas."""

import uuid

from pydantic import BaseModel


class DetectionRunResponse(BaseModel):
    rule_id: str
    rule_version: str
    events_scanned: int
    windows_detected: int
    alerts_created: int
    alerts_skipped_existing: int
    created_alert_ids: list[uuid.UUID]
