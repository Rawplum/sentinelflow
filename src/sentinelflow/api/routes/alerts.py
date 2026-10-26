"""Alert, evidence and investigation report API routes."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from sentinelflow.api.deps import request_metadata, require_permission
from sentinelflow.core.permissions import Permission
from sentinelflow.db.session import get_db
from sentinelflow.models.user import User
from sentinelflow.schemas.alerts import (
    DEFAULT_EVIDENCE_PAGE_SIZE,
    MAX_EVIDENCE_PAGE_SIZE,
    MAX_REPORT_EVIDENCE,
    AlertDetail,
    AlertEvidenceListResponse,
    AlertListResponse,
    AlertStatusHistoryRead,
    AlertStatusUpdateRequest,
    InvestigationReportListResponse,
    InvestigationReportRead,
    InvestigationReportResponse,
    ReportCreateRequest,
)
from sentinelflow.services.alerts import (
    InvalidStatusTransitionError,
    MissingTransitionReasonError,
    change_status,
    get_alert_read,
    get_status_history,
    list_alerts,
)
from sentinelflow.services.audit import record_audit
from sentinelflow.services.investigation_reports import (
    ReportConflictError,
    create_report_version,
    list_report_versions,
)
from sentinelflow.services.reports import (
    build_report,
    count_alert_evidence,
    load_alert_evidence,
    to_report_evidence,
)

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])


def _load_alert_detail(db: Session, alert_id: uuid.UUID) -> AlertDetail | None:
    alert = get_alert_read(db, alert_id)
    if alert is None:
        return None
    history = get_status_history(db, alert_id)
    return AlertDetail(
        **alert.model_dump(),
        status_history=[
            AlertStatusHistoryRead.model_validate(item) for item in history
        ],
    )


@router.get(
    "",
    response_model=AlertListResponse,
    summary="List alerts",
)
def list_alerts_endpoint(
    limit: Annotated[int, Query(ge=1, le=200, description="Page size")] = 50,
    offset: Annotated[int, Query(ge=0, description="Number of rows to skip")] = 0,
    user: User = Depends(require_permission(Permission.ALERTS_READ)),
    db: Session = Depends(get_db),
) -> AlertListResponse:
    items, total = list_alerts(db, limit=limit, offset=offset)
    return AlertListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{alert_id}",
    response_model=AlertDetail,
    summary="Get one alert with its status history",
    description=(
        "Authoritative alert metadata so clients can render an alert after a "
        "page refresh without relying on client-side routing state."
    ),
)
def get_alert_endpoint(
    alert_id: uuid.UUID,
    user: User = Depends(require_permission(Permission.ALERTS_READ)),
    db: Session = Depends(get_db),
) -> AlertDetail:
    detail = _load_alert_detail(db, alert_id)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert not found",
        )
    return detail


@router.patch(
    "/{alert_id}",
    response_model=AlertDetail,
    summary="Change an alert status",
    description=(
        "Applies a validated status transition (open, acknowledged, "
        "investigating, closed). Illegal transitions return 409. Every change "
        "writes alert status history and an audit record in one transaction. "
        "Admin only."
    ),
)
def update_alert_status_endpoint(
    alert_id: uuid.UUID,
    payload: AlertStatusUpdateRequest,
    request: Request,
    user: User = Depends(require_permission(Permission.ALERTS_WRITE)),
    db: Session = Depends(get_db),
) -> AlertDetail:
    try:
        result = change_status(
            db,
            alert_id,
            to_status=payload.status,
            user=user,
            reason=payload.reason,
            commit=False,
        )
    except InvalidStatusTransitionError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except MissingTransitionReasonError as exc:
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert not found",
        )

    source_ip, request_id = request_metadata(request)
    record_audit(
        db,
        actor_user_id=user.id,
        actor_username=user.username,
        action="alerts.status_change",
        outcome="success",
        resource_type="alert",
        resource_id=str(alert_id),
        source_ip=source_ip,
        request_id=request_id,
        details={
            "from_status": result.from_status,
            "to_status": result.to_status,
            "noop": not result.changed,
            "reason_provided": bool(payload.reason),
        },
    )
    db.commit()

    detail = _load_alert_detail(db, alert_id)
    if detail is None:  # pragma: no cover - defensive, the alert just committed
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert not found",
        )
    return detail


@router.get(
    "/{alert_id}/evidence",
    response_model=AlertEvidenceListResponse,
    summary="List one page of an alert's evidence events",
    description=(
        "Paginated evidence access. raw_message is excluded unless "
        "include_raw_message=true is requested."
    ),
)
def list_alert_evidence_endpoint(
    alert_id: uuid.UUID,
    limit: Annotated[
        int, Query(ge=1, le=MAX_EVIDENCE_PAGE_SIZE, description="Page size")
    ] = DEFAULT_EVIDENCE_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0, description="Number of rows to skip")] = 0,
    include_raw_message: Annotated[
        bool,
        Query(description="Include raw_message. Off by default for this endpoint."),
    ] = False,
    user: User = Depends(require_permission(Permission.ALERTS_READ)),
    db: Session = Depends(get_db),
) -> AlertEvidenceListResponse:
    alert = get_alert_read(db, alert_id)
    if alert is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert not found",
        )

    total = count_alert_evidence(db, alert_id)
    rows = load_alert_evidence(db, alert_id, limit=limit, offset=offset)
    items = [to_report_evidence(event) for event in rows]
    if not include_raw_message:
        items = [item.model_copy(update={"raw_message": None}) for item in items]
    return AlertEvidenceListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{alert_id}/report",
    response_model=InvestigationReportResponse,
    summary="Generate an investigation report",
    description=(
        "Generates a deterministic report from the alert and its evidence events. "
        "The report is computed on demand and is not persisted; use "
        "POST /api/v1/alerts/{alert_id}/reports to store a version. Evidence is "
        f"capped at {MAX_REPORT_EVIDENCE} rows per response."
    ),
)
def get_alert_report_endpoint(
    alert_id: uuid.UUID,
    request: Request,
    evidence_limit: Annotated[
        int,
        Query(
            ge=1,
            le=MAX_REPORT_EVIDENCE,
            description="Maximum evidence rows to embed",
        ),
    ] = MAX_REPORT_EVIDENCE,
    evidence_offset: Annotated[
        int, Query(ge=0, description="Evidence rows to skip")
    ] = 0,
    user: User = Depends(require_permission(Permission.REPORTS_READ)),
    db: Session = Depends(get_db),
) -> InvestigationReportResponse:
    report = build_report(
        db,
        alert_id,
        evidence_limit=evidence_limit,
        evidence_offset=evidence_offset,
    )
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert not found",
        )

    source_ip, request_id = request_metadata(request)
    record_audit(
        db,
        actor_user_id=user.id,
        actor_username=user.username,
        action="reports.view",
        outcome="success",
        resource_type="alert",
        resource_id=str(alert_id),
        source_ip=source_ip,
        request_id=request_id,
        details={
            "evidence_count": len(report.evidence),
            "evidence_total": report.evidence_total,
            "risk_level": report.risk_level,
        },
    )
    db.commit()

    return report


@router.get(
    "/{alert_id}/reports",
    response_model=InvestigationReportListResponse,
    summary="List persisted report versions for an alert",
)
def list_alert_reports_endpoint(
    alert_id: uuid.UUID,
    user: User = Depends(require_permission(Permission.REPORTS_READ)),
    db: Session = Depends(get_db),
) -> InvestigationReportListResponse:
    alert = get_alert_read(db, alert_id)
    if alert is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert not found",
        )
    items = list_report_versions(db, alert_id)
    return InvestigationReportListResponse(
        items=[InvestigationReportRead.model_validate(item) for item in items],
        total=len(items),
    )


@router.post(
    "/{alert_id}/reports",
    response_model=InvestigationReportRead,
    status_code=201,
    summary="Create a new draft report version",
    description=(
        "Builds the current deterministic report, stores it as a draft with the "
        "next version number, and records an input snapshot. Admin only."
    ),
)
def create_alert_report_endpoint(
    alert_id: uuid.UUID,
    request: Request,
    payload: ReportCreateRequest | None = None,
    user: User = Depends(require_permission(Permission.REPORTS_WRITE)),
    db: Session = Depends(get_db),
) -> InvestigationReportRead:
    try:
        report = create_report_version(db, alert_id, user=user, commit=False)
    except ReportConflictError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert not found",
        )

    source_ip, request_id = request_metadata(request)
    record_audit(
        db,
        actor_user_id=user.id,
        actor_username=user.username,
        action="reports.create",
        outcome="success",
        resource_type="alert",
        resource_id=str(alert_id),
        source_ip=source_ip,
        request_id=request_id,
        details={
            "report_id": str(report.id),
            "version": report.version,
            "generator": report.generator,
            "evidence_total": report.evidence_count,
            "evidence_truncated": report.evidence_truncated,
            "note_provided": bool(payload and payload.note),
        },
    )
    db.commit()
    db.refresh(report)
    return InvestigationReportRead.model_validate(report)
