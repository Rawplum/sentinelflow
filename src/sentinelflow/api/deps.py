"""Shared authentication and authorization dependencies."""

from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from sentinelflow.core.permissions import Permission, has_permission
from sentinelflow.core.security import (
    AuthConfigurationError,
    TokenValidationError,
    decode_access_token,
)
from sentinelflow.db.session import get_db
from sentinelflow.models.user import User
from sentinelflow.services.audit import record_audit
from sentinelflow.services.auth import is_token_revoked

bearer_scheme = HTTPBearer(auto_error=False)


def _credentials_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


def request_metadata(request: Request) -> tuple[str | None, str | None]:
    source_ip = request.client.host if request.client is not None else None
    if source_ip is not None:
        source_ip = source_ip[:45]
    request_id = getattr(request.state, "request_id", None)
    return source_ip, request_id


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _credentials_error()

    try:
        payload = decode_access_token(credentials.credentials)
    except AuthConfigurationError:
        raise
    except TokenValidationError:
        raise _credentials_error()

    try:
        user_id = uuid.UUID(str(payload["sub"]))
    except (KeyError, TypeError, ValueError):
        raise _credentials_error()

    # Revocation is checked against the database on every request so a logout
    # takes effect immediately rather than at token expiry.
    if is_token_revoked(db, str(payload.get("jti", ""))):
        raise _credentials_error()

    user = db.get(User, user_id)
    if user is None:
        raise _credentials_error()

    if not user.is_active:
        source_ip, request_id = request_metadata(request)
        record_audit(
            db,
            actor_user_id=user.id,
            actor_username=user.username,
            action="auth.inactive_user",
            outcome="denied",
            source_ip=source_ip,
            request_id=request_id,
            details={"reason": "inactive_account"},
        )
        db.commit()
        raise _credentials_error()

    return user


def require_permission(permission: Permission):
    """Return a dependency that requires an authenticated user with a permission."""

    def dependency(
        request: Request,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        if not has_permission(user.role, permission):
            source_ip, request_id = request_metadata(request)
            record_audit(
                db,
                actor_user_id=user.id,
                actor_username=user.username,
                action="authorization.denied",
                outcome="denied",
                resource_type="permission",
                resource_id=str(permission),
                source_ip=source_ip,
                request_id=request_id,
                details={
                    "role": user.role,
                    "method": request.method,
                    "path": request.url.path,
                },
            )
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden",
            )
        return user

    return dependency
