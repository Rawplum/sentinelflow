import json

import pytest
from sqlalchemy import select

from sentinelflow.cli import create_user as create_user_cli
from sentinelflow.core.permissions import UserRole
from sentinelflow.core.security import verify_password
from sentinelflow.models.audit_log import AuditLog
from sentinelflow.models.user import User
from sentinelflow.services.auth import UserAlreadyExistsError, create_user

PASSWORD = "cli-password-123"


def test_create_user_service_stores_hash_and_audit(session_factory) -> None:
    with session_factory() as session:
        user = create_user(
            session,
            username="cli.analyst",
            password=PASSWORD,
            role=UserRole.ANALYST,
        )
        user_id = user.id

    with session_factory() as session:
        stored = session.get(User, user_id)
        assert stored is not None
        assert stored.username == "cli.analyst"
        assert stored.role == "analyst"
        assert stored.password_hash != PASSWORD
        assert stored.password_hash.startswith("$argon2id$")
        assert verify_password(stored.password_hash, PASSWORD) is True

        audit = session.scalar(
            select(AuditLog).where(AuditLog.action == "users.create")
        )
        assert audit is not None
        assert audit.actor_username == "local-cli"
        assert audit.resource_type == "user"
        assert audit.resource_id == str(user_id)
        assert audit.details == {
            "created_username": "cli.analyst",
            "role": "analyst",
        }
        assert PASSWORD not in json.dumps(audit.details)


def test_duplicate_user_is_rejected(session_factory) -> None:
    with session_factory() as session:
        create_user(
            session,
            username="duplicate.user",
            password=PASSWORD,
            role=UserRole.ANALYST,
        )

    with session_factory() as session, pytest.raises(UserAlreadyExistsError):
        create_user(
            session,
            username="duplicate.user",
            password=PASSWORD,
            role=UserRole.ANALYST,
        )


@pytest.mark.parametrize(
    "username,password,role",
    [
        ("ab", PASSWORD, UserRole.ANALYST),
        ("bad name", PASSWORD, UserRole.ANALYST),
        ("valid.user", "short", UserRole.ANALYST),
        ("valid.user", PASSWORD, "owner"),
    ],
)
def test_invalid_user_input_is_rejected(
    session_factory, username, password, role
) -> None:
    with session_factory() as session, pytest.raises(ValueError):
        create_user(
            session,
            username=username,
            password=password,
            role=role,
        )


def test_cli_main_creates_user_without_printing_password(
    monkeypatch, session_factory, capsys
) -> None:
    monkeypatch.setattr(create_user_cli, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(create_user_cli.getpass, "getpass", lambda prompt="": PASSWORD)

    exit_code = create_user_cli.main(["--username", "cli.admin", "--role", "admin"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert PASSWORD not in captured.out
    assert PASSWORD not in captured.err

    with session_factory() as session:
        user = session.scalar(select(User).where(User.username == "cli.admin"))
        assert user is not None
        assert user.role == "admin"


def test_cli_created_user_can_login(
    monkeypatch, session_factory, client, capsys
) -> None:
    monkeypatch.setattr(create_user_cli, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(create_user_cli.getpass, "getpass", lambda prompt="": PASSWORD)
    assert create_user_cli.main(["--username", "cli.analyst", "--role", "analyst"]) == 0
    capsys.readouterr()

    response = client.post(
        "/api/v1/auth/login",
        json={"username": "cli.analyst", "password": PASSWORD},
    )

    assert response.status_code == 200
    assert response.json()["role"] == "analyst"


def test_cli_password_mismatch_does_not_create_user(
    monkeypatch, session_factory, capsys
) -> None:
    monkeypatch.setattr(create_user_cli, "get_session_factory", lambda: session_factory)
    values = iter(["first-password-123", "second-password-123"])
    monkeypatch.setattr(
        create_user_cli.getpass, "getpass", lambda prompt="": next(values)
    )

    exit_code = create_user_cli.main(
        ["--username", "mismatch.user", "--role", "analyst"]
    )

    assert exit_code == 1
    with session_factory() as session:
        assert (
            session.scalar(select(User).where(User.username == "mismatch.user")) is None
        )


def test_cli_does_not_accept_password_argument(monkeypatch, session_factory) -> None:
    monkeypatch.setattr(create_user_cli, "get_session_factory", lambda: session_factory)

    with pytest.raises(SystemExit):
        create_user_cli.main(
            [
                "--username",
                "argument.user",
                "--role",
                "analyst",
                "--password",
                "not-allowed-123",
            ]
        )
