import json
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from sqlalchemy import select

from sentinelflow.core.config import get_settings
from sentinelflow.core.security import (
    JWT_ALGORITHM,
    create_access_token,
    verify_password,
)
from sentinelflow.models.audit_log import AuditLog
from sentinelflow.models.user import User

ADMIN_PASSWORD = "admin-password-123"
INACTIVE_PASSWORD = "inactive-password-123"


def _login(client, username: str, password: str):
    return client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )


def test_login_success_returns_token(client, admin_user) -> None:
    response = _login(client, admin_user.username, ADMIN_PASSWORD)

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 1800
    assert body["username"] == admin_user.username
    assert body["role"] == "admin"
    assert body["access_token"]
    assert "password_hash" not in response.text


def test_login_wrong_password_returns_generic_401(client, admin_user) -> None:
    response = _login(client, admin_user.username, "wrong-password-123")

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid username or password"}
    assert "access_token" not in response.text


def test_login_unknown_user_returns_generic_401(client) -> None:
    response = _login(client, "nobody.test", "some-password-123")

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid username or password"}


def test_inactive_user_cannot_login(client, inactive_user) -> None:
    response = _login(client, inactive_user.username, INACTIVE_PASSWORD)

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid username or password"}


def test_me_requires_token(client) -> None:
    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_me_returns_current_user(admin_client) -> None:
    response = admin_client.get("/api/v1/auth/me")

    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "admin.test"
    assert body["role"] == "admin"
    assert body["is_active"] is True
    assert "password_hash" not in response.text


def test_missing_token_rejected_on_business_routes(
    client, event_factory
) -> None:
    event = event_factory()
    assert client.get("/api/v1/events").status_code == 401
    assert client.get("/api/v1/alerts").status_code == 401
    assert client.get("/api/v1/audit-logs").status_code == 401
    assert (
        client.get(f"/api/v1/alerts/{uuid.uuid4()}/report").status_code == 401
    )
    assert (
        client.post("/api/v1/events/import", json={"events": [event]}).status_code
        == 401
    )
    assert client.post("/api/v1/detections/run").status_code == 401


def test_invalid_token_rejected(client) -> None:
    response = client.get(
        "/api/v1/events",
        headers={"Authorization": "Bearer not-a-valid-token"},
    )

    assert response.status_code == 401


def _encode_token(secret: str, **overrides) -> str:
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
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def test_expired_token_rejected(client) -> None:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    token = _encode_token(
        settings.jwt_secret.get_secret_value(),
        iat=now - timedelta(minutes=10),
        exp=now - timedelta(minutes=5),
    )

    response = client.get(
        "/api/v1/events",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


def test_wrong_signature_rejected(client) -> None:
    token = _encode_token("another-secret-0123456789abcdef0123456789")

    response = client.get(
        "/api/v1/events",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


def test_inactive_user_token_rejected(
    client, inactive_user, db_session
) -> None:
    token, _ = create_access_token(inactive_user)

    response = client.get(
        "/api/v1/events",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401
    db_session.expire_all()
    audit = db_session.scalar(
        select(AuditLog).where(AuditLog.action == "auth.inactive_user")
    )
    assert audit is not None
    assert audit.outcome == "denied"


def test_role_change_is_effective_immediately(
    client, admin_token, admin_user, db_session
) -> None:
    stored = db_session.get(User, admin_user.id)
    assert stored is not None
    stored.role = "analyst"
    db_session.commit()

    headers = {"Authorization": f"Bearer {admin_token}"}
    assert client.get("/api/v1/events", headers=headers).status_code == 200

    denied = client.post("/api/v1/detections/run", headers=headers)
    assert denied.status_code == 403
    assert denied.json() == {"detail": "Forbidden"}

    db_session.expire_all()
    audit = db_session.scalar(
        select(AuditLog).where(AuditLog.action == "authorization.denied")
    )
    assert audit is not None
    assert audit.actor_username == "admin.test"
    assert audit.resource_id == "detections:run"


def test_login_success_and_failure_are_audited(
    client, admin_user, db_session
) -> None:
    assert _login(client, admin_user.username, ADMIN_PASSWORD).status_code == 200
    assert _login(client, admin_user.username, "wrong-password-123").status_code == 401

    db_session.expire_all()
    success = db_session.scalar(
        select(AuditLog).where(AuditLog.action == "auth.login")
    )
    failure = db_session.scalar(
        select(AuditLog).where(AuditLog.action == "auth.login_failed")
    )

    assert success is not None
    assert success.outcome == "success"
    assert success.actor_username == admin_user.username
    assert success.details == {"role": "admin"}

    assert failure is not None
    assert failure.outcome == "failure"
    assert failure.actor_username is None
    assert failure.details == {"reason": "invalid_credentials"}
    assert "wrong-password-123" not in json.dumps(failure.details)


def test_login_validation_error_does_not_echo_password(client) -> None:
    password = "x" * 129
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin.test", "password": password},
    )

    assert response.status_code == 422
    assert password not in response.text
    assert '"input"' not in response.text


def test_auth_not_configured_returns_503(
    monkeypatch, client, admin_user
) -> None:
    monkeypatch.delenv("JWT_SECRET", raising=False)
    get_settings.cache_clear()
    try:
        response = _login(client, admin_user.username, ADMIN_PASSWORD)
    finally:
        get_settings.cache_clear()

    assert response.status_code == 503
    assert response.json() == {"detail": "Authentication is not configured"}
    assert "access_token" not in response.text


def test_no_public_registration_route(client) -> None:
    assert client.post("/api/v1/auth/register", json={}).status_code == 404
    assert client.post("/api/v1/register", json={}).status_code == 404


def test_password_is_stored_as_hash(admin_user, db_session) -> None:
    db_session.expire_all()
    stored = db_session.get(User, admin_user.id)

    assert stored is not None
    assert stored.password_hash != ADMIN_PASSWORD
    assert stored.password_hash.startswith("$argon2id$")
    assert verify_password(stored.password_hash, ADMIN_PASSWORD) is True
