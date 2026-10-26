import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
import pytest

from sentinelflow.core.config import get_settings
from sentinelflow.core.permissions import Permission, UserRole, has_permission
from sentinelflow.core.security import (
    JWT_ALGORITHM,
    AuthConfigurationError,
    InvalidUsernameError,
    TokenValidationError,
    WeakPasswordError,
    create_access_token,
    decode_access_token,
    hash_password,
    normalize_username,
    validate_username,
    verify_password,
)

PASSWORD = "correct-password-123"


def test_argon2_hash_is_not_plaintext() -> None:
    password_hash = hash_password(PASSWORD)

    assert password_hash != PASSWORD
    assert password_hash.startswith("$argon2id$")
    assert verify_password(password_hash, PASSWORD) is True
    assert verify_password(password_hash, "wrong-password-123") is False


def test_password_hashes_use_unique_salts() -> None:
    assert hash_password(PASSWORD) != hash_password(PASSWORD)


def test_short_password_is_rejected() -> None:
    with pytest.raises(WeakPasswordError):
        hash_password("short")


def test_username_normalization_and_validation() -> None:
    assert normalize_username(" Admin.Test ") == "admin.test"
    assert validate_username(" Admin.Test ") == "admin.test"

    with pytest.raises(InvalidUsernameError):
        validate_username("ab")
    with pytest.raises(InvalidUsernameError):
        validate_username("bad name")
    assert validate_username("Admin") == "admin"


def test_permission_matrix() -> None:
    for permission in Permission:
        assert has_permission(UserRole.ADMIN.value, permission) is True

    assert has_permission(UserRole.ANALYST.value, Permission.EVENTS_READ) is True
    assert has_permission(UserRole.ANALYST.value, Permission.ALERTS_READ) is True
    assert has_permission(UserRole.ANALYST.value, Permission.REPORTS_READ) is True
    assert has_permission(UserRole.ANALYST.value, Permission.EVENTS_IMPORT) is False
    assert has_permission(UserRole.ANALYST.value, Permission.DETECTIONS_RUN) is False
    assert has_permission(UserRole.ANALYST.value, Permission.AUDIT_READ) is False
    assert has_permission("unknown", Permission.EVENTS_READ) is False


def test_token_round_trip() -> None:
    user = SimpleNamespace(id=uuid.uuid4(), role="admin")

    token, expires_in = create_access_token(user)
    payload = decode_access_token(token)

    assert expires_in == 1800
    assert payload["sub"] == str(user.id)
    assert payload["role"] == "admin"
    assert payload["type"] == "access"


def _encode_token(**overrides) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(uuid.uuid4()),
        "role": "admin",
        "iat": now,
        "exp": now + timedelta(minutes=30),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "type": "access",
    }
    payload.update(overrides)
    return jwt.encode(
        payload,
        settings.jwt_secret.get_secret_value(),
        algorithm=JWT_ALGORITHM,
    )


def test_expired_token_is_rejected() -> None:
    now = datetime.now(timezone.utc)
    token = _encode_token(
        iat=now - timedelta(minutes=10),
        exp=now - timedelta(minutes=5),
    )

    with pytest.raises(TokenValidationError):
        decode_access_token(token)


def test_wrong_signature_is_rejected() -> None:
    settings = get_settings()
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "role": "admin",
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "type": "access",
        },
        "another-secret-0123456789abcdef0123456789",
        algorithm=JWT_ALGORITHM,
    )

    with pytest.raises(TokenValidationError):
        decode_access_token(token)


def test_wrong_audience_is_rejected() -> None:
    with pytest.raises(TokenValidationError):
        decode_access_token(_encode_token(aud="another-audience"))


def test_wrong_issuer_is_rejected() -> None:
    with pytest.raises(TokenValidationError):
        decode_access_token(_encode_token(iss="another-issuer"))


def test_non_access_token_is_rejected() -> None:
    with pytest.raises(TokenValidationError):
        decode_access_token(_encode_token(type="refresh"))


def test_missing_jwt_secret_fails_closed(monkeypatch) -> None:
    monkeypatch.delenv("JWT_SECRET", raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(AuthConfigurationError):
            create_access_token(SimpleNamespace(id=uuid.uuid4(), role="admin"))
    finally:
        get_settings.cache_clear()


def test_short_jwt_secret_fails_closed(monkeypatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "too-short")
    get_settings.cache_clear()
    try:
        with pytest.raises(AuthConfigurationError):
            decode_access_token("not-a-real-token")
    finally:
        get_settings.cache_clear()
