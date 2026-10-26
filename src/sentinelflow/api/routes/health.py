"""Liveness and readiness endpoints."""

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import literal, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from sentinelflow import __version__
from sentinelflow.core.config import Settings, get_settings
from sentinelflow.db.session import get_db
from sentinelflow.schemas.health import HealthResponse, ReadinessResponse

router = APIRouter(tags=["system"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness check",
    description=(
        "Liveness only: reports that the API process is running. It never "
        "touches the database, so a database outage does not restart a healthy "
        "container. Use /health/ready before sending traffic."
    ),
)
def health_check(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=__version__,
        environment=settings.app_env,
    )


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    summary="Readiness check",
    description=(
        "Liveness plus one round trip to the database. Returns 503 with "
        "status='degraded' when the database cannot be reached, so a load "
        "balancer or compose healthcheck can hold traffic back. The error text "
        "is deliberately generic: it must not leak a connection string."
    ),
    responses={503: {"description": "A dependency is unavailable"}},
)
def readiness_check(
    response: Response,
    settings: Settings = Depends(get_settings),
    session: Session = Depends(get_db),
) -> ReadinessResponse:
    try:
        session.execute(select(literal(1)))
    except SQLAlchemyError:
        # Never echo the driver message: it can contain the DSN with a password.
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(
            status="degraded",
            service=settings.app_name,
            version=__version__,
            database="unavailable",
            detail="database is not reachable",
        )

    return ReadinessResponse(
        status="ready",
        service=settings.app_name,
        version=__version__,
        database="ok",
    )
