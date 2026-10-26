"""Health and liveness endpoint."""

from fastapi import APIRouter, Depends

from sentinelflow import __version__
from sentinelflow.core.config import Settings, get_settings
from sentinelflow.schemas.health import HealthResponse

router = APIRouter(tags=["system"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness check",
    description=(
        "Reports that the API process is running. It does not check database "
        "connectivity; readiness checks will be added with the data layer."
    ),
)
def health_check(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=__version__,
        environment=settings.app_env,
    )
