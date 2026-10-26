"""Agent investigation API routes.

An investigation is created synchronously (so the client gets an id and can
poll) and executed in a background task with its own session. This keeps a long
model run from holding the request open, and lets the UI show real progress.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from sentinelflow.ai.model_client import (
    ModelClient,
    ModelNotConfiguredError,
    build_model_client,
)
from sentinelflow.api.deps import request_metadata, require_permission
from sentinelflow.core.config import get_settings
from sentinelflow.core.permissions import Permission
from sentinelflow.db.session import get_db
from sentinelflow.models.investigation import Investigation
from sentinelflow.models.user import User
from sentinelflow.schemas.investigations import (
    InvestigationRead,
    InvestigationRoundRead,
    InvestigationToolCallRead,
)
from sentinelflow.services.audit import record_audit
from sentinelflow.services.investigations import (
    InvestigationConflictError,
    InvestigationQueueFullError,
    create_investigation,
    get_investigation,
    list_rounds,
    list_tool_calls,
    recover_stale_investigation,
)

router = APIRouter(prefix="/api/v1", tags=["investigations"])


def provide_model_client() -> ModelClient:
    """FastAPI dependency so tests can inject a scripted model client."""
    return build_model_client()


def _to_read(db: Session, investigation: Investigation) -> InvestigationRead:
    rounds = list_rounds(db, investigation.id)
    calls = list_tool_calls(db, investigation.id)
    return InvestigationRead(
        **{
            key: getattr(investigation, key)
            for key in (
                "id",
                "alert_id",
                "status",
                "model_provider",
                "model_name",
                "prompt_version",
                "rounds_used",
                "tool_calls_used",
                "error",
                "error_code",
                "attempt_count",
                "max_attempts",
                "request_id",
                "duration_ms",
                "report_id",
                "created_by_username",
                "created_at",
                "started_at",
                "completed_at",
            )
        },
        rounds=[InvestigationRoundRead.model_validate(item) for item in rounds],
        tool_calls=[InvestigationToolCallRead.model_validate(item) for item in calls],
    )


@router.post(
    "/alerts/{alert_id}/investigations",
    response_model=InvestigationRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue a bounded AI agent investigation",
    description=(
        "Stores the investigation as 'pending' and returns 202 immediately. A "
        "durable queue worker claims it (status 'running') and executes it; poll "
        "GET /api/v1/investigations/{id} until the status is terminal. The "
        "request itself never calls the model, so a slow provider cannot time "
        "out the HTTP call. Admin only."
    ),
    responses={
        503: {"description": "Model provider is not configured"},
        404: {"description": "Alert not found"},
        409: {"description": "Another investigation is already running"},
        429: {"description": "Investigation queue is full"},
    },
)
def run_investigation_endpoint(
    alert_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_permission(Permission.REPORTS_WRITE)),
    db: Session = Depends(get_db),
    client: ModelClient = Depends(provide_model_client),
) -> InvestigationRead:
    source_ip, request_id = request_metadata(request)

    try:
        investigation = create_investigation(
            db,
            alert_id,
            user=user,
            client=client,
            request_id=request_id,
        )
    except InvestigationConflictError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except InvestigationQueueFullError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
            headers={"Retry-After": "60"},
        ) from exc

    if investigation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert not found",
        )

    record_audit(
        db,
        actor_user_id=user.id,
        actor_username=user.username,
        action="investigations.run",
        outcome="success",
        resource_type="alert",
        resource_id=str(alert_id),
        source_ip=source_ip,
        request_id=request_id,
        details={
            "investigation_id": str(investigation.id),
            "status": investigation.status,
            "queued": True,
        },
    )
    db.commit()
    db.refresh(investigation)

    # The task is now durable: the queue worker picks it up. The request never
    # runs the model, so it cannot time out on a slow provider.
    return _to_read(db, investigation)


@router.get(
    "/investigations/{investigation_id}",
    response_model=InvestigationRead,
    summary="Read an investigation, its rounds and its tool-call log",
    description=(
        "Returns the task status, per-round model latency, per-tool-call duration "
        "and sanitized error summaries. A task stuck in 'running' past the "
        "configured timeout is reported as failed instead of hanging forever."
    ),
)
def get_investigation_endpoint(
    investigation_id: uuid.UUID,
    user: User = Depends(require_permission(Permission.REPORTS_READ)),
    db: Session = Depends(get_db),
) -> InvestigationRead:
    investigation = get_investigation(db, investigation_id)
    if investigation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Investigation not found",
        )

    settings = get_settings()
    if recover_stale_investigation(
        db,
        investigation,
        stale_after_seconds=settings.agent_stale_after_seconds,
    ):
        db.refresh(investigation)

    return _to_read(db, investigation)


__all__ = ["ModelNotConfiguredError", "provide_model_client", "router"]
