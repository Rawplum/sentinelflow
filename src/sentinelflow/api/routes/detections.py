"""Deterministic detection API routes."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from sentinelflow.api.deps import request_metadata, require_permission
from sentinelflow.core.permissions import Permission
from sentinelflow.db.session import get_db
from sentinelflow.models.user import User
from sentinelflow.schemas.detections import DetectionRunResponse
from sentinelflow.services.audit import record_audit
from sentinelflow.services.detection import (
    RULE_ID,
    RULE_VERSION,
)
from sentinelflow.services.detection import (
    run_detection as run_detection_service,
)

router = APIRouter(prefix="/api/v1/detections", tags=["detections"])


@router.post(
    "/run",
    response_model=DetectionRunResponse,
    summary="Run the deterministic detection rule (admin only)",
    description=(
        "Scans imported authentication failures with the AUTH-001 rule. "
        "Re-running on the same data does not create duplicate alerts."
    ),
)
def run_detection_endpoint(
    request: Request,
    user: User = Depends(require_permission(Permission.DETECTIONS_RUN)),
    db: Session = Depends(get_db),
) -> DetectionRunResponse:
    result = run_detection_service(db, commit=False)

    source_ip, request_id = request_metadata(request)
    record_audit(
        db,
        actor_user_id=user.id,
        actor_username=user.username,
        action="detections.run",
        outcome="success",
        source_ip=source_ip,
        request_id=request_id,
        details={
            "events_scanned": result.events_scanned,
            "windows_detected": result.windows_detected,
            "alerts_created": result.alerts_created,
            "alerts_skipped_existing": result.alerts_skipped_existing,
        },
    )
    db.commit()

    return DetectionRunResponse(
        rule_id=RULE_ID,
        rule_version=RULE_VERSION,
        events_scanned=result.events_scanned,
        windows_detected=result.windows_detected,
        alerts_created=result.alerts_created,
        alerts_skipped_existing=result.alerts_skipped_existing,
        created_alert_ids=result.created_alert_ids,
    )
