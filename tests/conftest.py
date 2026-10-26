from __future__ import annotations

import os
import secrets
import threading
import uuid
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event as sqlalchemy_event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import sentinelflow.models  # noqa: F401  (registers ORM tables)
from sentinelflow.core.config import get_settings
from sentinelflow.core.permissions import UserRole
from sentinelflow.core.security import hash_password
from sentinelflow.db.session import Base, get_db
from sentinelflow.main import create_app
from sentinelflow.models.alert import Alert
from sentinelflow.models.security_event import SecurityEvent
from sentinelflow.models.user import User

from support.stub_provider import StubProvider

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
# Test-only secret generated per test process. Never use outside the test suite.
TEST_JWT_SECRET = "test-jwt-secret-" + secrets.token_urlsafe(32)
ADMIN_PASSWORD = "admin-password-123"
ANALYST_PASSWORD = "analyst-password-123"
INACTIVE_PASSWORD = "inactive-password-123"


def _build_engine():
    if TEST_DATABASE_URL:
        if "test" not in TEST_DATABASE_URL.lower():
            raise RuntimeError(
                "TEST_DATABASE_URL must point to a dedicated test database"
            )
        return create_engine(TEST_DATABASE_URL, pool_pre_ping=True)

    sqlite_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @sqlalchemy_event.listens_for(sqlite_engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return sqlite_engine


engine = _build_engine()
SessionFactory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture(scope="session", autouse=True)
def prepare_database() -> Iterator[None]:
    Base.metadata.create_all(engine)
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Keep tests independent of a developer's local .env file."""
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
    # The queue worker is a thread; tests drain the queue explicitly instead so
    # they never depend on thread timing.
    monkeypatch.setenv("AGENT_WORKER_ENABLED", "false")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def clean_database(prepare_database: None) -> Iterator[None]:
    with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(table.delete())
    yield


@pytest.fixture()
def app():
    from support import configure

    application = create_app()
    configure(application, SessionFactory)

    def override_get_db() -> Iterator[Session]:
        with SessionFactory() as session:
            yield session

    application.dependency_overrides[get_db] = override_get_db
    yield application
    application.dependency_overrides.clear()


@pytest.fixture()
def client(app) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def session_factory():
    return SessionFactory


@pytest.fixture()
def user_factory():
    def make(
        *,
        username: str,
        password: str,
        role: UserRole | str,
        is_active: bool = True,
    ) -> User:
        with SessionFactory() as session:
            user = User(
                username=username,
                password_hash=hash_password(password),
                role=UserRole(role).value,
                is_active=is_active,
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            return user

    return make


@pytest.fixture()
def admin_user(user_factory) -> User:
    return user_factory(
        username="admin.test",
        password=ADMIN_PASSWORD,
        role=UserRole.ADMIN,
    )


@pytest.fixture()
def analyst_user(user_factory) -> User:
    return user_factory(
        username="analyst.test",
        password=ANALYST_PASSWORD,
        role=UserRole.ANALYST,
    )


@pytest.fixture()
def inactive_user(user_factory) -> User:
    return user_factory(
        username="inactive.test",
        password=INACTIVE_PASSWORD,
        role=UserRole.ANALYST,
        is_active=False,
    )


@pytest.fixture()
def stub_provider():
    """A local OpenAI-compatible stub. Not a real model."""
    server = StubProvider()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.fixture()
def admin_password() -> str:
    """Password for the ``admin_user`` fixture, without importing conftest."""
    return ADMIN_PASSWORD


@pytest.fixture()
def analyst_password() -> str:
    return ANALYST_PASSWORD


def _login(client: TestClient, username: str, password: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.fixture()
def admin_token(client, admin_user) -> str:
    return _login(client, admin_user.username, ADMIN_PASSWORD)


@pytest.fixture()
def analyst_token(client, analyst_user) -> str:
    return _login(client, analyst_user.username, ANALYST_PASSWORD)


@pytest.fixture()
def admin_client(app, admin_token) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        test_client.headers.update(
            {"Authorization": f"Bearer {admin_token}"}
        )
        yield test_client


@pytest.fixture()
def analyst_client(app, analyst_token) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        test_client.headers.update(
            {"Authorization": f"Bearer {analyst_token}"}
        )
        yield test_client


@pytest.fixture()
def db_session() -> Iterator[Session]:
    with SessionFactory() as session:
        yield session


@pytest.fixture()
def alert_factory():
    """Create an alert with a controllable number of linked evidence events.

    Building the rows directly keeps pagination and status tests fast and lets
    them exceed the report evidence cap without importing hundreds of events
    through the API.
    """

    def make(
        *,
        evidence_count: int = 5,
        status: str = "open",
        severity: str = "high",
        username: str = "alice.demo",
        source_ip: str = "198.51.100.10",
        rule_id: str = "AUTH-001",
    ) -> uuid.UUID:
        base = datetime(2026, 10, 19, 9, 0, tzinfo=timezone.utc)
        with SessionFactory() as session:
            events = [
                SecurityEvent(
                    event_id=uuid.uuid4(),
                    timestamp=base + timedelta(minutes=index),
                    event_type="authentication",
                    username=username,
                    source_ip=source_ip,
                    asset_id="asset-01",
                    action="login",
                    outcome="failure",
                    raw_message=f"synthetic failure {index}",
                    source="synthetic-auth",
                )
                for index in range(evidence_count)
            ]
            session.add_all(events)
            alert = Alert(
                rule_id=rule_id,
                rule_version="1.0.0",
                title="Suspicious login activity",
                description=(
                    f"{evidence_count} failed authentication attempts for user "
                    f"'{username}' from {source_ip} matched rule {rule_id}."
                ),
                severity=severity,
                status=status,
                first_seen_at=base,
                last_seen_at=base + timedelta(minutes=max(evidence_count - 1, 0)),
                event_count=evidence_count,
                dedup_key=f"{rule_id}:{uuid.uuid4().hex}",
            )
            alert.evidence_events = events
            session.add(alert)
            session.commit()
            return alert.id

    return make


@pytest.fixture()
def event_factory():
    def make(**overrides):
        event_id = overrides.pop("event_id", uuid.uuid4())
        timestamp = overrides.pop(
            "timestamp", datetime(2026, 10, 19, 9, 0, tzinfo=timezone.utc)
        )
        payload = {
            "event_id": str(event_id),
            "timestamp": timestamp.isoformat()
            if isinstance(timestamp, datetime)
            else timestamp,
            "event_type": "authentication",
            "username": "alice.demo",
            "source_ip": "198.51.100.10",
            "asset_id": "asset-01",
            "action": "login",
            "outcome": "failure",
            "raw_message": "synthetic authentication failure",
            "source": "synthetic-auth",
        }
        payload.update(overrides)
        payload["event_id"] = str(payload["event_id"])
        if isinstance(payload["timestamp"], datetime):
            payload["timestamp"] = payload["timestamp"].isoformat()
        return payload

    return make


@pytest.fixture()
def failure_batch(event_factory):
    def make(
        *,
        count: int = 5,
        username: str = "alice.demo",
        source_ip: str = "198.51.100.10",
        start: datetime | None = None,
        step: timedelta = timedelta(minutes=1),
        outcome: str = "failure",
    ) -> list[dict]:
        first = start or datetime(2026, 10, 19, 9, 0, tzinfo=timezone.utc)
        return [
            event_factory(
                event_id=uuid.uuid4(),
                timestamp=first + step * index,
                username=username,
                source_ip=source_ip,
                outcome=outcome,
                raw_message=f"synthetic {outcome} for {username}",
            )
            for index in range(count)
        ]

    return make
