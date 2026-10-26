"""Password hashing, JWT issuance/validation, and username policy."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Protocol

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from sentinelflow.core.config import get_settings

JWT_ALGORITHM = "HS256"
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128
MIN_USERNAME_LENGTH = 3
MAX_USERNAME_LENGTH = 64
USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")


class AuthConfigurationError(RuntimeError):
    """Authentication configuration is missing or invalid."""


class TokenValidationError(Exception):
    """A bearer token is missing required properties or is invalid."""


class InvalidUsernameError(ValueError):
    """A username does not satisfy the local account policy."""


class WeakPasswordError(ValueError):
    """A new password does not satisfy the local password policy."""


class TokenSubject(Protocol):
    id: Any
    role: str


_hasher = PasswordHasher()


def normalize_username(username: str) -> str:
    return username.strip().lower()


def validate_username(username: str) -> str:
    normalized = normalize_username(username)
    if not USERNAME_PATTERN.fullmatch(normalized):
        raise InvalidUsernameError(
            "username must be 3-64 characters using lowercase letters, digits, "
            "dots, underscores, or hyphens, and must start with a letter or digit"
        )
    return normalized


def validate_new_password(password: str) -> None:
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise WeakPasswordError(
            f"password must be between {MIN_PASSWORD_LENGTH} and "
            f"{MAX_PASSWORD_LENGTH} characters"
        )


def hash_password(password: str) -> str:
    validate_new_password(password)
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    # Perform Argon2 work for unknown usernames so login timing does not reveal
    # whether an account exists. The input is a fixed non-secret placeholder.
    return _hasher.hash("sentinelflow-dummy-password")


def verify_password_or_dummy(password_hash: str | None, password: str) -> bool:
    if password_hash is None:
        verify_password(_dummy_hash(), password)
        return False
    return verify_password(password_hash, password)


def get_jwt_secret() -> str:
    settings = get_settings()
    if settings.jwt_secret is None:
        raise AuthConfigurationError("JWT_SECRET is not configured")
    secret = settings.jwt_secret.get_secret_value()
    if len(secret) < 32:
        raise AuthConfigurationError("JWT_SECRET must be at least 32 characters")
    return secret


def ensure_auth_configured() -> None:
    get_jwt_secret()


def create_access_token(user: TokenSubject) -> tuple[str, int]:
    settings = get_settings()
    secret = get_jwt_secret()
    now = datetime.now(timezone.utc)
    expires_delta = timedelta(minutes=settings.access_token_expire_minutes)
    payload = {
        "sub": str(user.id),
        "role": str(user.role),
        "iat": now,
        "exp": now + expires_delta,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "type": "access",
        # Unique token identifier so a single token can be revoked without
        # invalidating every token issued to the same user.
        "jti": str(uuid.uuid4()),
    }
    token = jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)
    return token, int(expires_delta.total_seconds())


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    secret = get_jwt_secret()
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[JWT_ALGORITHM],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={
                "require": ["exp", "iat", "sub", "iss", "aud", "type", "jti"],
            },
        )
    except jwt.InvalidTokenError as exc:
        raise TokenValidationError("Could not validate credentials") from exc

    if payload.get("type") != "access":
        raise TokenValidationError("Could not validate credentials")
    return payload


def token_expires_at(payload: dict[str, Any]) -> datetime:
    """Return the token expiry as an aware UTC datetime."""
    return datetime.fromtimestamp(int(payload["exp"]), tz=timezone.utc)
