"""Login throttling, token revocation and logout tests."""

from datetime import UTC, datetime, timedelta

import jwt
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from sentinelflow.core.config import get_settings
from sentinelflow.core.security import JWT_ALGORITHM, get_jwt_secret
from sentinelflow.models.audit_log import AuditLog
from sentinelflow.models.revoked_token import RevokedToken


def _login(client: TestClient, username: str, password: str):
    return client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )


def test_repeated_failures_are_throttled(client, admin_user) -> None:
    for _ in range(5):
        assert _login(client, admin_user.username, "wrong-password").status_code == 401

    blocked = _login(client, admin_user.username, "wrong-password")

    assert blocked.status_code == 429
    assert blocked.json()["detail"] == "Too many login attempts. Try again later."
    assert int(blocked.headers["Retry-After"]) > 0


def test_correct_password_is_also_blocked_while_throttled(
    client, admin_user, admin_password
) -> None:
    for _ in range(5):
        _login(client, admin_user.username, "wrong-password")

    blocked = _login(client, admin_user.username, admin_password)

    assert blocked.status_code == 429


def test_successful_login_resets_the_counter(
    client, admin_user, admin_password
) -> None:
    for _ in range(4):
        _login(client, admin_user.username, "wrong-password")

    assert _login(client, admin_user.username, admin_password).status_code == 200

    for _ in range(4):
        assert _login(client, admin_user.username, "wrong-password").status_code == 401


def test_throttling_is_per_subject(
    client, admin_user, analyst_user, admin_password, analyst_password
) -> None:
    for _ in range(5):
        _login(client, admin_user.username, "wrong-password")

    assert _login(client, admin_user.username, admin_password).status_code == 429
    assert _login(client, analyst_user.username, analyst_password).status_code == 200


def test_throttle_audit_does_not_store_username(
    client, admin_user, session_factory
) -> None:
    for _ in range(5):
        _login(client, admin_user.username, "wrong-password")
    _login(client, admin_user.username, "wrong-password")

    with session_factory() as session:
        entry = session.scalars(
            select(AuditLog).where(AuditLog.action == "auth.login_throttled")
        ).one()

    assert entry.actor_username is None
    assert entry.outcome == "denied"
    assert entry.details["retry_after_seconds"] > 0
    assert "wrong-password" not in str(entry.details)


def test_logout_revokes_token(admin_client, session_factory) -> None:
    assert admin_client.get("/api/v1/auth/me").status_code == 200

    response = admin_client.post("/api/v1/auth/logout")

    assert response.status_code == 204
    assert admin_client.get("/api/v1/auth/me").status_code == 401


def test_revoked_token_cannot_access_protected_api(admin_client) -> None:
    assert admin_client.get("/api/v1/alerts").status_code == 200
    admin_client.post("/api/v1/auth/logout")

    assert admin_client.get("/api/v1/alerts").status_code == 401
    assert admin_client.get("/api/v1/events").status_code == 401
    assert admin_client.get("/api/v1/audit-logs").status_code == 401


def test_logout_stores_only_the_token_identifier(admin_client, session_factory) -> None:
    token = admin_client.headers["Authorization"].split(" ", 1)[1]
    admin_client.post("/api/v1/auth/logout")

    with session_factory() as session:
        entries = session.scalars(select(RevokedToken)).all()

    assert len(entries) == 1
    assert entries[0].reason == "logout"
    assert entries[0].expires_at is not None
    # The JWT itself must never be persisted.
    assert token not in str(entries[0].jti)
    assert len(str(entries[0].jti)) == 36


def test_logout_twice_returns_401(admin_client) -> None:
    assert admin_client.post("/api/v1/auth/logout").status_code == 204
    assert admin_client.post("/api/v1/auth/logout").status_code == 401


def test_logout_requires_authentication(client) -> None:
    assert client.post("/api/v1/auth/logout").status_code == 401


def test_logout_writes_audit(admin_client, session_factory) -> None:
    admin_client.post("/api/v1/auth/logout")

    with session_factory() as session:
        entries = session.scalars(
            select(AuditLog).where(AuditLog.action == "auth.logout")
        ).all()

    assert len(entries) == 1
    assert entries[0].actor_username == "admin.test"
    assert entries[0].outcome == "success"


def test_revoking_one_token_does_not_affect_another(
    client, admin_user, admin_password
) -> None:
    first = _login(client, admin_user.username, admin_password).json()["access_token"]
    second = _login(client, admin_user.username, admin_password).json()["access_token"]
    assert first != second

    assert (
        client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {first}"},
        ).status_code
        == 204
    )

    assert (
        client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {first}"}
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {second}"}
        ).status_code
        == 200
    )


def test_token_carries_unique_identifier(client, admin_user, admin_password) -> None:
    token = _login(client, admin_user.username, admin_password).json()["access_token"]
    payload = jwt.decode(token, options={"verify_signature": False})

    assert payload["jti"]
    assert payload["exp"] > payload["iat"]


def test_token_without_jti_is_rejected(client, admin_user) -> None:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(admin_user.id),
        "role": "admin",
        "iat": now,
        "exp": now + timedelta(minutes=30),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "type": "access",
    }
    legacy = jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)

    response = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {legacy}"}
    )

    assert response.status_code == 401


def test_throttle_table_stores_no_plaintext(
    client, admin_user, session_factory
) -> None:
    from sentinelflow.models.login_attempt import LoginAttempt

    _login(client, admin_user.username, "wrong-password")

    with session_factory() as session:
        attempts = session.scalars(select(LoginAttempt)).all()

    assert len(attempts) == 1
    assert attempts[0].subject_hash != admin_user.username
    assert admin_user.username not in attempts[0].subject_hash
    assert attempts[0].succeeded is False


def test_successful_login_records_success(
    client, admin_user, admin_password, session_factory
) -> None:
    from sentinelflow.models.login_attempt import LoginAttempt

    _login(client, admin_user.username, admin_password)

    with session_factory() as session:
        total = session.scalar(select(func.count()).select_from(LoginAttempt))

    # The success path clears failure counters, so no failure rows remain.
    assert total == 0
