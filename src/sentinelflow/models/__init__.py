"""SQLAlchemy ORM models.

Importing this package registers every table on ``Base.metadata`` so Alembic
autogenerate can see the complete schema.
"""

from sentinelflow.models.alert import Alert, alert_events
from sentinelflow.models.alert_status_history import AlertStatusHistory
from sentinelflow.models.audit_log import AuditLog
from sentinelflow.models.investigation import (
    Investigation,
    InvestigationRound,
    InvestigationToolCall,
)
from sentinelflow.models.investigation_report import InvestigationReport
from sentinelflow.models.login_attempt import LoginAttempt
from sentinelflow.models.revoked_token import RevokedToken
from sentinelflow.models.security_event import SecurityEvent
from sentinelflow.models.user import User

__all__ = [
    "Alert",
    "AlertStatusHistory",
    "AuditLog",
    "Investigation",
    "InvestigationReport",
    "InvestigationRound",
    "InvestigationToolCall",
    "LoginAttempt",
    "RevokedToken",
    "SecurityEvent",
    "User",
    "alert_events",
]
