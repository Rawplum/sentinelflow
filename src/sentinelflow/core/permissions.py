"""Central role and permission definitions.

Routes must use these permissions through the shared authorization dependency
instead of comparing role strings directly.
"""

from enum import StrEnum


class UserRole(StrEnum):
    ADMIN = "admin"
    ANALYST = "analyst"


class Permission(StrEnum):
    EVENTS_READ = "events:read"
    EVENTS_IMPORT = "events:import"
    DETECTIONS_RUN = "detections:run"
    ALERTS_READ = "alerts:read"
    ALERTS_WRITE = "alerts:write"
    REPORTS_READ = "reports:read"
    REPORTS_WRITE = "reports:write"
    REPORTS_FINALIZE = "reports:finalize"
    AUDIT_READ = "audit:read"


ROLE_PERMISSIONS: dict[UserRole, frozenset[Permission]] = {
    UserRole.ADMIN: frozenset(Permission),
    # Analysts stay read-only. Mutating an alert's status, creating report
    # versions and finalizing a report are all state changes that require an
    # accountable operator; granting them to analysts needs a separate
    # ownership model that does not exist yet.
    UserRole.ANALYST: frozenset(
        {
            Permission.EVENTS_READ,
            Permission.ALERTS_READ,
            Permission.REPORTS_READ,
        }
    ),
}


def has_permission(role: str, permission: Permission) -> bool:
    try:
        role_enum = UserRole(role)
    except ValueError:
        return False
    return permission in ROLE_PERMISSIONS[role_enum]
