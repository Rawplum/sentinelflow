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
