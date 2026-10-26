from fastapi.testclient import TestClient

from sentinelflow import __version__


def test_health_returns_expected_payload(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {
        "status": "ok",
        "service": "SentinelFlow",
        "version": __version__,
        "environment": "test",
    }


def test_health_does_not_require_database_configuration(client: TestClient) -> None:
    # The test fixture removes DATABASE_URL; liveness must not depend on it.
    assert client.get("/health").status_code == 200


def test_openapi_documents_health_endpoint(client: TestClient) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/health" in response.json()["paths"]


# --- readiness --------------------------------------------------------------


def test_readiness_reports_ready_with_a_working_database(client: TestClient) -> None:
    response = client.get("/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["database"] == "ok"
    assert body["detail"] is None


def test_readiness_returns_503_when_the_database_is_down(app, client) -> None:
    from sqlalchemy.exc import SQLAlchemyError

    from sentinelflow.db.session import get_db

    class BrokenSession:
        def execute(self, *_args, **_kwargs):
            # A driver message that contains the DSN, as psycopg's often does.
            raise SQLAlchemyError(
                "could not connect: postgresql://user:hunter2@db:5432/x"
            )

    app.dependency_overrides[get_db] = lambda: BrokenSession()
    try:
        response = client.get("/health/ready")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["database"] == "unavailable"
    # The probe is unauthenticated: it must never echo the connection string.
    assert "hunter2" not in response.text


def test_liveness_stays_up_when_the_database_is_down(app, client) -> None:
    """A database outage must not make the container look dead."""
    from sqlalchemy.exc import SQLAlchemyError

    from sentinelflow.db.session import get_db

    class BrokenSession:
        def execute(self, *_args, **_kwargs):
            raise SQLAlchemyError("down")

    app.dependency_overrides[get_db] = lambda: BrokenSession()
    try:
        assert client.get("/health").status_code == 200
        assert client.get("/health/ready").status_code == 503
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_readiness_is_not_behind_authentication(client: TestClient) -> None:
    """Probes cannot carry a token, so this path must be public."""
    spec = client.get("/openapi.json").json()

    assert "/health/ready" in spec["paths"]
    assert spec["paths"]["/health/ready"]["get"].get("security") in (None, [])
