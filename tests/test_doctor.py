"""The doctor has to be right, because a wrong answer sends people the wrong way.

These tests do not need a database: they feed each check the state a broken
install would have and assert the advice. One test uses the real test engine to
confirm an unmigrated schema is reported as such.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from sentinelflow.cli import doctor
from sentinelflow.core.config import get_settings


def _config_with(monkeypatch, secret: str | None) -> tuple:
    if secret is None:
        monkeypatch.delenv("JWT_SECRET", raising=False)
    else:
        monkeypatch.setenv("JWT_SECRET", secret)
    get_settings.cache_clear()
    try:
        return doctor.check_config()
    finally:
        get_settings.cache_clear()


def test_missing_secret_is_a_failure_with_a_generator_command(monkeypatch) -> None:
    check, _ = _config_with(monkeypatch, None)

    assert check.status == doctor.FAIL
    assert "JWT_SECRET is not set" in check.detail
    assert "secrets.token_urlsafe" in (check.advice or "")


def test_short_secret_is_rejected(monkeypatch) -> None:
    check, _ = _config_with(monkeypatch, "too-short")

    assert check.status == doctor.FAIL
    assert "must be at least 32" in (check.advice or "")


def test_example_secret_is_rejected(monkeypatch) -> None:
    """The value in .env.example is public; starting with it must not pass."""
    check, _ = _config_with(monkeypatch, "CHANGE_ME" + "x" * 40)

    assert check.status == doctor.FAIL
    assert "example value" in check.detail


def test_a_real_secret_passes(monkeypatch) -> None:
    check, settings = _config_with(monkeypatch, "a" * 48)

    assert check.status == doctor.OK
    assert settings is not None


def test_empty_database_url_is_a_failure() -> None:
    check, engine = doctor.check_database("")

    assert check.status == doctor.FAIL
    assert engine is None
    assert "DATABASE_URL is not set" in check.detail


def test_unreachable_database_reports_the_cause_without_the_password() -> None:
    # Port 1 is closed; the connection fails immediately.
    check, engine = doctor.check_database(
        "postgresql+psycopg://user:hunter2@127.0.0.1:1/nothing"
    )

    assert check.status == doctor.FAIL
    assert engine is None
    assert "hunter2" not in check.detail, "the password must be masked"
    assert "***" in check.detail


def test_missing_migration_is_reported_with_the_command() -> None:
    """A schema created without alembic has no alembic_version row."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    try:
        check = doctor.check_migrations(engine)
    finally:
        engine.dispose()

    assert check.status == doctor.FAIL
    assert "alembic upgrade head" in (check.advice or "")


def test_main_returns_two_when_something_failed(monkeypatch, capsys) -> None:
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    try:
        code = doctor.main([])
    finally:
        get_settings.cache_clear()

    out = capsys.readouterr().out
    assert code == 2
    assert "check(s) failed" in out
    # The report must name every failing check, not stop at the first.
    assert "config" in out and "database" in out


def test_masking_keeps_the_shape_but_not_the_secret() -> None:
    masked = doctor._mask_dsn(
        "postgresql+psycopg://sentinelflow:hunter2@db.internal:5432/sentinelflow"
    )

    assert "hunter2" not in masked
    assert masked == "postgresql+psycopg://sentinelflow:***@db.internal:5432/sentinelflow"


def test_masking_a_dsn_without_a_password_is_a_no_op() -> None:
    dsn = "postgresql+psycopg://sentinelflow@127.0.0.1:5432/sentinelflow"

    assert doctor._mask_dsn(dsn) == dsn
