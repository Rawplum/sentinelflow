"""Security event API routes."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import AwareDatetime
from sqlalchemy.orm import Session

from sentinelflow.api.deps import request_metadata, require_permission
from sentinelflow.core.permissions import Permission
from sentinelflow.core.time import as_utc
from sentinelflow.db.session import get_db
from sentinelflow.models.user import User
from sentinelflow.schemas.events import (
    EventImportRequest,
    EventImportResponse,
    EventListResponse,
    SecurityEventRead,
)
from sentinelflow.services.audit import record_audit
from sentinelflow.services.events import EventFilters, import_events, list_events

router = APIRouter(prefix="/api/v1/events", tags=["events"])


@router.post(
    "/import",
    response_model=EventImportResponse,
    status_code=201,
    summary="Import validated security events",
    description=(
        "Imports up to 500 validated events. Duplicate event_id values are "
        "skipped, making retries idempotent. Admin only."
    ),
)
def import_events_endpoint(
    payload: EventImportRequest,
    request: Request,
    user: User = Depends(require_permission(Permission.EVENTS_IMPORT)),
    db: Session = Depends(get_db),
) -> EventImportResponse:
    result = import_events(db, payload.events, commit=False)

    source_ip, request_id = request_metadata(request)
    record_audit(
        db,
        actor_user_id=user.id,
        actor_username=user.username,
        action="events.import",
        outcome="success",
        source_ip=source_ip,
        request_id=request_id,
        details={
            "received": result.received,
            "imported": result.imported,
            "skipped": result.skipped,
        },
    )
    db.commit()

    return EventImportResponse(
        received=result.received,
        imported=result.imported,
        skipped=result.skipped,
        skipped_event_ids=result.skipped_event_ids,
    )


@router.get(
    "",
    response_model=EventListResponse,
    summary="List security events",
    description=(
        "Paginated event search. Every filter is optional and applied as a "
        "parameterized SQL predicate. The keyword filter matches raw_message "
        "only. raw_message is omitted when include_raw_message=false."
    ),
)
def list_events_endpoint(
    limit: Annotated[int, Query(ge=1, le=200, description="Page size")] = 50,
    offset: Annotated[int, Query(ge=0, description="Number of rows to skip")] = 0,
    event_type: Annotated[
        str | None, Query(max_length=100, description="Exact event_type match")
    ] = None,
    username: Annotated[
        str | None, Query(max_length=255, description="Exact username match")
    ] = None,
    source_ip: Annotated[
        str | None, Query(max_length=45, description="Exact source_ip match")
    ] = None,
    asset_id: Annotated[
        str | None, Query(max_length=255, description="Exact asset_id match")
    ] = None,
    action: Annotated[
        str | None, Query(max_length=100, description="Exact action match")
    ] = None,
    outcome: Annotated[
        Literal["success", "failure", "unknown"] | None,
        Query(description="Exact outcome match"),
    ] = None,
    q: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=200,
            description="Case-insensitive substring match on raw_message",
        ),
    ] = None,
    start: Annotated[
        AwareDatetime | None,
        Query(description="Only events at or after this UTC timestamp"),
    ] = None,
    end: Annotated[
        AwareDatetime | None,
        Query(description="Only events at or before this UTC timestamp"),
    ] = None,
    include_raw_message: Annotated[
        bool,
        Query(description="Set false to omit raw_message from the response"),
    ] = True,
    user: User = Depends(require_permission(Permission.EVENTS_READ)),
    db: Session = Depends(get_db),
) -> EventListResponse:
    if start is not None and end is not None and start > end:
        raise HTTPException(
            status_code=422,
            detail="'start' must not be after 'end'",
        )

    filters = EventFilters(
        event_type=event_type,
        username=username,
        source_ip=source_ip,
        asset_id=asset_id,
        action=action,
        outcome=outcome,
        keyword=q,
        start=as_utc(start) if start is not None else None,
        end=as_utc(end) if end is not None else None,
    )
    items, total = list_events(db, limit=limit, offset=offset, filters=filters)

    payload = []
    for item in items:
        read = SecurityEventRead.model_validate(item)
        if not include_raw_message:
            read = read.model_copy(update={"raw_message": None})
        payload.append(read)

    return EventListResponse(
        items=payload,
        total=total,
        limit=limit,
        offset=offset,
    )
