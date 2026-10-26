"""Schemas for system endpoints."""

from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str = Field(examples=["SentinelFlow"])
    version: str = Field(examples=["0.1.0"])
    environment: str = Field(examples=["development"])


class ReadinessResponse(BaseModel):
    """Readiness: the process is up *and* its dependencies answer."""

    status: Literal["ready", "degraded"]
    service: str = Field(examples=["SentinelFlow"])
    version: str = Field(examples=["0.1.0"])
    database: Literal["ok", "unavailable"]
    detail: str | None = None
