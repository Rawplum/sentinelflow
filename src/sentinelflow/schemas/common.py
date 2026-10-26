"""Shared schema helpers."""

from datetime import datetime
from typing import Annotated

from pydantic import BeforeValidator

from sentinelflow.core.time import as_utc


def _normalize_datetime(value: object) -> object:
    if isinstance(value, datetime):
        return as_utc(value)
    return value


UTCDateTime = Annotated[datetime, BeforeValidator(_normalize_datetime)]
