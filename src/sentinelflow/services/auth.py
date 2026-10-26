"""Authentication, login throttling, token revocation and user management."""

from __future__ import annotations

import hashlib
import hmac
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sentinelflow.core.config import get_settings
from sentinelflow.core.permissions import UserRole
from sentinelflow.core.security import (
    create_access_token,
    ensure_auth_configured,
    get_jwt_secret,
    hash_password,
    normalize_username,
    token_expires_at,
    validate_username,
    verify_password_or_dummy,
)
from sentinelflow.core.time import utcnow
from sentinelflow.models.login_attempt import LoginAttempt
from sentinelflow.models.revoked_token import RevokedToken
from sentinelflow.models.user import User
from sentinelflow.services.audit import record_audit


class UserAlreadyExistsError(ValueError):
    """A local username is already in use."""


class LoginThrottledError(Exception):
    """Too many failed login attempts for this account/IP pair."""

    def __init__(self, retry_after: int) -> None:
        super().__init__("Too many login attempts")
        self.retry_after = retry_after


@dataclass(frozen=True)
class LoginResult:
    user: User
    access_token: str
    expires_in: int


def get_user_by_id(session: Session, user_id: uuid.UUID) -> User | None:
    return session.get(User, user_id)


# --- Login throttling -------------------------------------------------------
#
# Attempts are hashed with HMAC keyed by the JWT secret so the table never
# stores plaintext usernames or IPs. The counter lives in the database rather
# than in process memory, so it is shared by every worker that uses the same
# database. It does NOT protect against an attacker who can write to that
# database, and it adds one read plus one write per login attempt.


def _throttle_key() -> bytes:
    return get_jwt_secret().encode("utf-8")


def _hmac(value: str) -> str:
    return hmac.new(_throttle_key(), value.encode("utf-8"), hashlib.sha256).hexdigest()


def subject_hash(username: str, source_ip: str | None) -> str:
    return _hmac(f"subject|{normalize_username(username)}|{source_ip or ''}")


def ip_hash(source_ip: str | None) -> str | None:
    if not source_ip:
        return None
    return _hmac(f"ip|{source_ip}")


def _window_start(now: datetime) -> datetime:
    window = get_settings().login_rate_limit_window_seconds
    return now - timedelta(seconds=window)


def _count_failures(session: Session, column, value, since: datetime) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(LoginAttempt)
            .where(
                column == value,
                LoginAttempt.succeeded.is_(False),
                LoginAttempt.attempted_at >= since,
            )
        )
        or 0
    )


def check_login_throttle(
    session: Session,
    *,
    username: str,
    source_ip: str | None,
    now: datetime | None = None,
) -> int | None:
    """Return seconds to wait when throttled, otherwise ``None``.

    Two independent limits apply: one per (username, IP) pair and a looser one
    per source IP so a single host cannot spray many account names.
    """
    settings = get_settings()
    now = now or utcnow()
    since = _window_start(now)
    window = settings.login_rate_limit_window_seconds

    subject = subject_hash(username, source_ip)
    # Opportunistic pruning keeps the table bounded without a scheduler.
    session.execute(
        delete(LoginAttempt).where(
            LoginAttempt.subject_hash == subject,
            LoginAttempt.attempted_at < since - timedelta(seconds=window),
        )
    )

    failures = _count_failures(session, LoginAttempt.subject_hash, subject, since)
    if failures >= settings.login_rate_limit_attempts:
        return window

    ip_digest = ip_hash(source_ip)
    if ip_digest is not None:
        ip_failures = _count_failures(
            session, LoginAttempt.ip_hash, ip_digest, since
        )
        if ip_failures >= settings.login_rate_limit_ip_attempts:
            return window

    return None


def record_login_attempt(
    session: Session,
    *,
    username: str,
    source_ip: str | None,
    succeeded: bool,
) -> None:
    session.add(
        LoginAttempt(
            subject_hash=subject_hash(username, source_ip),
            ip_hash=ip_hash(source_ip),
            succeeded=succeeded,
            attempted_at=utcnow(),
        )
    )


def reset_login_attempts(
    session: Session, *, username: str, source_ip: str | None
) -> None:
    """Clear the failure counter after a successful login."""
    session.execute(
        delete(LoginAttempt).where(
            LoginAttempt.subject_hash == subject_hash(username, source_ip),
            LoginAttempt.succeeded.is_(False),
        )
    )


# --- Token revocation -------------------------------------------------------


def revoke_token(
    session: Session,
    *,
    payload: dict,
    user_id: uuid.UUID | None,
    reason: str = "logout",
    commit: bool = False,
) -> RevokedToken | None:
    """Record a token's ``jti`` as revoked.

    Only the identifier and expiry are stored; the token itself is never
    persisted. Returns ``None`` when the identifier was already revoked.
    """
    jti = uuid.UUID(str(payload["jti"]))
    if session.get(RevokedToken, jti) is not None:
        return None

    entry = RevokedToken(
        jti=jti,
        user_id=user_id,
        expires_at=token_expires_at(payload),
        revoked_at=utcnow(),
        reason=reason,
    )
    session.add(entry)
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError:
        # Concurrent logout for the same token; treat as already revoked.
        return None

    if commit:
        session.commit()
    return entry


def is_token_revoked(session: Session, jti: str) -> bool:
    """Return True when the token identifier is revoked or malformed.

    A malformed ``jti`` fails closed: every token this service issues carries a
    UUID identifier, so anything else is not a token we can reason about.
    """
    try:
        parsed = uuid.UUID(str(jti))
    except (TypeError, ValueError):
        return True
    return session.get(RevokedToken, parsed) is not None


# --- Login ------------------------------------------------------------------


def _record_login_failure(
    session: Session,
    *,
    user: User | None,
    username: str,
    source_ip: str | None,
    request_id: str | None,
    reason: str,
) -> None:
    # Do not store the attempted username in the audit log. For a known account
    # the internal user ID links the failure without exposing the account name.
    record_login_attempt(
        session,
        username=username,
        source_ip=source_ip,
        succeeded=False,
    )
    record_audit(
        session,
        actor_user_id=user.id if user is not None else None,
        actor_username=None,
        action="auth.login_failed",
        outcome="failure",
        source_ip=source_ip,
        request_id=request_id,
        details={"reason": reason},
    )
    session.commit()


def authenticate_and_issue_token(
    session: Session,
    *,
    username: str,
    password: str,
    source_ip: str | None = None,
    request_id: str | None = None,
) -> LoginResult | None:
    ensure_auth_configured()

    normalized = normalize_username(username)

    retry_after = check_login_throttle(
        session,
        username=normalized,
        source_ip=source_ip,
    )
    if retry_after is not None:
        record_audit(
            session,
            actor_user_id=None,
            actor_username=None,
            action="auth.login_throttled",
            outcome="denied",
            source_ip=source_ip,
            request_id=request_id,
            details={"retry_after_seconds": retry_after},
        )
        session.commit()
        raise LoginThrottledError(retry_after)

    user = session.scalar(select(User).where(User.username == normalized))
    password_valid = verify_password_or_dummy(
        user.password_hash if user is not None else None,
        password,
    )

    if user is None or not password_valid:
        _record_login_failure(
            session,
            user=user,
            username=normalized,
            source_ip=source_ip,
            request_id=request_id,
            reason="invalid_credentials",
        )
        return None

    if not user.is_active:
        _record_login_failure(
            session,
            user=user,
            username=normalized,
            source_ip=source_ip,
            request_id=request_id,
            reason="inactive_account",
        )
        return None

    reset_login_attempts(session, username=normalized, source_ip=source_ip)
    access_token, expires_in = create_access_token(user)
    user.last_login_at = utcnow()
    record_audit(
        session,
        actor_user_id=user.id,
        actor_username=user.username,
        action="auth.login",
        outcome="success",
        source_ip=source_ip,
        request_id=request_id,
        details={"role": user.role},
    )
    session.commit()
    return LoginResult(
        user=user,
        access_token=access_token,
        expires_in=expires_in,
    )


def create_user(
    session: Session,
    *,
    username: str,
    password: str,
    role: UserRole | str,
    actor_username: str = "local-cli",
) -> User:
    normalized = validate_username(username)
    try:
        role_value = UserRole(role).value
    except ValueError as exc:
        raise ValueError("role must be 'admin' or 'analyst'") from exc

    password_hash = hash_password(password)

    existing = session.scalar(select(User).where(User.username == normalized))
    if existing is not None:
        raise UserAlreadyExistsError(f"user '{normalized}' already exists")

    user = User(
        username=normalized,
        password_hash=password_hash,
        role=role_value,
        is_active=True,
    )
    session.add(user)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise UserAlreadyExistsError(f"user '{normalized}' already exists") from exc

    record_audit(
        session,
        actor_user_id=None,
        actor_username=actor_username,
        action="users.create",
        outcome="success",
        resource_type="user",
        resource_id=str(user.id),
        details={"created_username": user.username, "role": user.role},
    )
    session.commit()
    return user
