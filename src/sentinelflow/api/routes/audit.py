"""Audit log query API routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from sentinelflow.api.deps import request_metadata, require_permission
from sentinelflow.core.permissions import Permission
from sentinelflow.db.session import get_db
from sentinelflow.models.user import User
from sentinelflow.schemas.audit import AuditLogListResponse, AuditLogRead
from sentinelflow.services.audit import list_audit_logs, record_audit

router = APIRouter(prefix="/api/v1/audit-logs", tags=["audit"])


@router.get(
    "",
    response_model=AuditLogListResponse,
    summary="List audit records (admin only)",
)
def list_audit_logs_endpoint(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=200, description="Page size")] = 50,
    offset: Annotated[int, Query(ge=0, description="Number of rows to skip")] = 0,
    action: Annotated[
        str | None,
        Query(max_length=64, description="Optional exact action filter"),
    ] = None,
    user: User = Depends(require_permission(Permission.AUDIT_READ)),
    db: Session = Depends(get_db),
) -> AuditLogListResponse:
    items, total = list_audit_logs(
        db,
        limit=limit,
        offset=offset,
        action=action,
    )

    source_ip, request_id = request_metadata(request)
    record_audit(
        db,
        actor_user_id=user.id,
        actor_username=user.username,
        action="audit.view",
        outcome="success",
        source_ip=source_ip,
        request_id=request_id,
        details={
            "action_filter": action,
            "limit": limit,
            "offset": offset,
        },
    )
    db.commit()

    return AuditLogListResponse(
        items=[AuditLogRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )
