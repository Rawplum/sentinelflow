"""Authentication API routes."""

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from sentinelflow.api.deps import (
    bearer_scheme,
    get_current_user,
    request_metadata,
)
from sentinelflow.core.permissions import UserRole
from sentinelflow.core.security import decode_access_token
from sentinelflow.db.session import get_db
from sentinelflow.models.user import User
from sentinelflow.schemas.auth import LoginRequest, TokenResponse, UserRead
from sentinelflow.services.audit import record_audit
from sentinelflow.services.auth import (
    LoginThrottledError,
    authenticate_and_issue_token,
    revoke_token,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Exchange local credentials for a bearer token",
    responses={429: {"description": "Too many failed login attempts"}},
)
def login_endpoint(
    payload: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> TokenResponse:
    source_ip, request_id = request_metadata(request)
    try:
        result = authenticate_and_issue_token(
            db,
            username=payload.username,
            password=payload.password.get_secret_value(),
            source_ip=source_ip,
            request_id=request_id,
        )
    except LoginThrottledError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Try again later.",
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return TokenResponse(
        access_token=result.access_token,
        expires_in=result.expires_in,
        username=result.user.username,
        role=UserRole(result.user.role),
    )


@router.get(
    "/me",
    response_model=UserRead,
    summary="Return the authenticated user",
)
def me_endpoint(user: User = Depends(get_current_user)) -> UserRead:
    return UserRead.model_validate(user)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke the current access token",
    description=(
        "Records the token identifier as revoked. The token stops working "
        "immediately, before its expiry. Only the identifier is stored; the "
        "token itself is never persisted."
    ),
)
def logout_endpoint(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    if credentials is None:  # pragma: no cover - get_current_user rejects first
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        )

    payload = decode_access_token(credentials.credentials)
    revoke_token(db, payload=payload, user_id=user.id, reason="logout")

    source_ip, request_id = request_metadata(request)
    record_audit(
        db,
        actor_user_id=user.id,
        actor_username=user.username,
        action="auth.logout",
        outcome="success",
        source_ip=source_ip,
        request_id=request_id,
        details={"jti": str(payload.get("jti"))},
    )
    db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
