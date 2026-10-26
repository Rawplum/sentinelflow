"""Schemas for system endpoints."""

from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str = Field(examples=["SentinelFlow"])
    version: str = Field(examples=["0.1.0"])
    environment: str = Field(examples=["development"])
