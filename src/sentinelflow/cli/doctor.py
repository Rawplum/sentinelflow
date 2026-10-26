"""Check that this machine can actually run SentinelFlow.

The failure modes for a first run are boring and repetitive: no .env, a
password that does not match, PostgreSQL not listening, migrations not applied,
no user to log in as. Each one produces a stack trace far from its cause.

``sentinelflow-doctor`` runs the same checks in the same order a new user would
hit them, and prints what to do next. It never writes anything and never prints
a secret.

Exit codes: 0 when nothing is broken, 2 when a check failed.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from sentinelflow.core.config import Settings, get_settings

OK = "OK  "
WARN = "WARN"
INFO = "INFO"
FAIL = "FAIL"

MIN_PYTHON = (3, 11)
MIN_SECRET_LENGTH = 32


@dataclass
class Check:
    name: str
    status: str
    detail: str
    #: What the reader should do about it, printed only for WARN/FAIL.
    advice: str | None = None


def _mask_dsn(dsn: str) -> str:
    """Hide the password in a connection string before printing it."""
    try:
        parts = urlsplit(dsn)
    except ValueError:
        return "<unparsable DATABASE_URL>"
    if parts.password is None:
        return dsn
    netloc = f"{parts.username or ''}:***@{parts.hostname or ''}"
    if parts.port:
        netloc += f":{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def check_python() -> Check:
    version = sys.version_info
    text_version = f"{version.major}.{version.minor}.{version.micro}"
    if (version.major, version.minor) < MIN_PYTHON:
        return Check(
            "python",
            FAIL,
            text_version,
            f"SentinelFlow needs Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer",
        )
    return Check("python", OK, text_version)


def check_config() -> tuple[Check, Settings | None]:
    """Load settings and validate the JWT secret the way signing would."""
    try:
        settings = get_settings()
    except Exception as exc:
        return (
            Check(
                "config",
                FAIL,
                f"settings did not load: {type(exc).__name__}",
                "check .env against .env.example",
            ),
            None,
        )

    if settings.jwt_secret is None:
        return (
            Check(
                "config",
                FAIL,
                "JWT_SECRET is not set",
                'run: python -c "import secrets; print(secrets.token_urlsafe(48))" '
                "and put the output in .env",
            ),
            settings,
        )

    secret = settings.jwt_secret.get_secret_value()
    if len(secret) < MIN_SECRET_LENGTH:
        return (
            Check(
                "config",
                FAIL,
                f"JWT_SECRET is {len(secret)} characters",
                f"it must be at least {MIN_SECRET_LENGTH}",
            ),
            settings,
        )
    if secret.strip().lower().startswith("change_me"):
        return (
            Check(
                "config",
                FAIL,
                "JWT_SECRET is still the example value",
                "generate a real one; the example is public",
            ),
            settings,
        )

    return Check("config", OK, "JWT_SECRET set"), settings


def check_database(dsn: str) -> tuple[Check, Engine | None]:
    """Open one connection and run SELECT 1."""
    if not dsn:
        return (
            Check(
                "database",
                FAIL,
                "DATABASE_URL is not set",
                "set it in .env; PostgreSQL 16 is required",
            ),
            None,
        )

    # A doctor that hangs is worse than one that fails: cap the connect wait so
    # "PostgreSQL is not running" comes back in seconds, not minutes.
    connect_args = {}
    if dsn.startswith("postgresql"):
        connect_args["connect_timeout"] = 5

    try:
        engine = create_engine(dsn, pool_pre_ping=True, connect_args=connect_args)
    except Exception as exc:
        return (
            Check(
                "database",
                FAIL,
                f"cannot build an engine: {type(exc).__name__}",
                "check the DATABASE_URL scheme, e.g. postgresql+psycopg://...",
            ),
            None,
        )

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        # The driver message can contain the DSN, so report the type only.
        return (
            Check(
                "database",
                FAIL,
                f"{_mask_dsn(dsn)} unreachable ({type(exc).__name__})",
                "is PostgreSQL running, and does the password match?",
            ),
            None,
        )

    return Check("database", OK, _mask_dsn(dsn)), engine


def check_migrations(engine: Engine) -> Check:
    """Compare alembic_version with the newest revision on disk."""
    try:
        tables = set(inspect(engine).get_table_names())
    except SQLAlchemyError:
        return Check("migrations", FAIL, "cannot read the schema", "check the database")

    if "alembic_version" not in tables:
        return Check(
            "migrations",
            FAIL,
            "no alembic_version table",
            "run: alembic upgrade head",
        )

    with engine.connect() as connection:
        current = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one_or_none()

    head = _head_revision()
    if head is None:
        return Check(
            "migrations",
            WARN,
            f"database at {current}, cannot read migrations/",
            "run the doctor from the repository root to compare with head",
        )
    if current != head:
        return Check(
            "migrations",
            FAIL,
            f"database at {current}, code expects {head}",
            "run: alembic upgrade head",
        )

    return Check("migrations", OK, f"{current} (head)")


def _head_revision() -> str | None:
    """Read the head revision from migrations/, if we are in the repo."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config_path = Path("alembic.ini")
    if not config_path.is_file():
        return None
    try:
        config = Config(str(config_path))
        config.set_main_option("script_location", "migrations")
        return ScriptDirectory.from_config(config).get_current_head()
    except Exception:
        return None


def check_users(engine: Engine) -> Check:
    with engine.connect() as connection:
        count = connection.execute(text("SELECT count(*) FROM users")).scalar_one()
    if count == 0:
        return Check(
            "users",
            WARN,
            "no users yet",
            "run: sentinelflow-create-user --username admin --role admin",
        )
    return Check("users", OK, f"{count} user(s)")


def check_agent(settings: Settings) -> Check:
    configured = bool(
        settings.llm_provider
        and settings.llm_model
        and settings.llm_api_base
        and settings.llm_api_key is not None
    )
    if not configured:
        return Check(
            "agent",
            INFO,
            "disabled (LLM_* not set); the API works, investigations return 503",
        )
    return Check("agent", OK, f"{settings.llm_provider} / {settings.llm_model}")


def check_console() -> Check:
    node_modules = Path("frontend/node_modules")
    if not Path("frontend").is_dir():
        return Check("console", INFO, "frontend/ not present; API only")
    if not node_modules.is_dir():
        return Check(
            "console",
            WARN,
            "frontend/node_modules missing",
            "cd frontend && npm install",
        )
    return Check("console", OK, "dependencies installed")


def run_checks() -> list[Check]:
    checks = [check_python()]

    config_check, settings = check_config()
    checks.append(config_check)

    engine = None
    if settings is not None:
        database_check, engine = check_database(settings.database_url or "")
        checks.append(database_check)

    if engine is not None:
        checks.append(check_migrations(engine))
        try:
            checks.append(check_users(engine))
        except SQLAlchemyError:
            checks.append(
                Check(
                    "users",
                    FAIL,
                    "cannot read the users table",
                    "run: alembic upgrade head",
                )
            )
        engine.dispose()

    if settings is not None:
        checks.append(check_agent(settings))
    checks.append(check_console())
    return checks


def _next_step(checks: list[Check]) -> str | None:
    for check in checks:
        if check.status in (FAIL, WARN) and check.advice:
            return check.advice
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check whether this machine can run SentinelFlow."
    )
    parser.parse_args(argv)

    checks = run_checks()

    width = max(len(check.name) for check in checks)
    print("SentinelFlow doctor")
    for check in checks:
        print(f"  {check.status}  {check.name.ljust(width)}  {check.detail}")
        if check.status in (FAIL, WARN) and check.advice:
            print(f"        {' ' * width}  -> {check.advice}")

    failures = [check for check in checks if check.status == FAIL]
    print()
    if failures:
        print(f"{len(failures)} check(s) failed.")
        return 2

    next_step = _next_step(checks)
    if next_step:
        print(f"Ready, with warnings. Next: {next_step}")
    else:
        print("All checks passed. Start the API with:")
        print("  uvicorn sentinelflow.main:app --host 127.0.0.1 --port 8000")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
