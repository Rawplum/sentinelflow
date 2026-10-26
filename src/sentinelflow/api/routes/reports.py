"""Persisted investigation report routes."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from sentinelflow.api.deps import request_metadata, require_permission
from sentinelflow.core.permissions import Permission
from sentinelflow.db.session import get_db
from sentinelflow.models.user import User
from sentinelflow.schemas.alerts import InvestigationReportRead
from sentinelflow.services.audit import record_audit
from sentinelflow.services.investigation_reports import (
    ReportConflictError,
    finalize_report,
    get_report,
)

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])


@router.get(
    "/{report_id}",
    response_model=InvestigationReportRead,
    summary="Read a persisted report version",
    description=(
        "Returns the stored report body and the input snapshot it was generated "
        "from. The snapshot is frozen at creation time and may differ from the "
        "current database rows for the same events."
    ),
)
def get_report_endpoint(
    report_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_permission(Permission.REPORTS_READ)),
    db: Session = Depends(get_db),
) -> InvestigationReportRead:
    report = get_report(db, report_id)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report not found",
        )

    source_ip, request_id = request_metadata(request)
    record_audit(
        db,
        actor_user_id=user.id,
        actor_username=user.username,
        action="reports.read",
        outcome="success",
        resource_type="report",
        resource_id=str(report_id),
        source_ip=source_ip,
        request_id=request_id,
        details={"version": report.version, "status": report.status},
    )
    db.commit()

    return InvestigationReportRead.model_validate(report)


@router.post(
    "/{report_id}/finalize",
    response_model=InvestigationReportRead,
    summary="Finalize a draft report version",
    description=(
        "Marks a draft as finalized and supersedes the previously finalized "
        "version of the same alert. A finalized report is never edited in place; "
        "create a new version to revise it. Admin only."
    ),
)
def finalize_report_endpoint(
    report_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_permission(Permission.REPORTS_FINALIZE)),
    db: Session = Depends(get_db),
) -> InvestigationReportRead:
    try:
        report = finalize_report(db, report_id, user=user, commit=False)
    except ReportConflictError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report not found",
        )

    source_ip, request_id = request_metadata(request)
    record_audit(
        db,
        actor_user_id=user.id,
        actor_username=user.username,
        action="reports.finalize",
        outcome="success",
        resource_type="report",
        resource_id=str(report_id),
        source_ip=source_ip,
        request_id=request_id,
        details={
            "alert_id": str(report.alert_id),
            "version": report.version,
        },
    )
    db.commit()
    db.refresh(report)
    return InvestigationReportRead.model_validate(report)
