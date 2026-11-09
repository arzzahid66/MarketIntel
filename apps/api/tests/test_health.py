from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_is_live(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["environment"] == "test"
    # The server, not the browser, is the clock for "last updated X min ago".
    assert body["server_time"].endswith(("Z", "+00:00"))


def test_readiness_reports_database_and_seed_state(client: TestClient) -> None:
    body = client.get("/health/ready").json()
    assert body["database"] == "ok"
    assert body["plans_seeded"] is True
    assert body["status"] == "ok"


def test_every_response_carries_a_request_id(client: TestClient) -> None:
    response = client.get("/health")
    assert response.headers.get("X-Request-ID")


def test_supplied_request_id_is_echoed(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "abc-123"})
    assert response.headers["X-Request-ID"] == "abc-123"


def test_intentional_error_returns_the_error_envelope(client: TestClient) -> None:
    """Phase 1 exit criterion: the Sentry drill endpoint raises, and the handler
    converts it to a clean envelope rather than leaking a traceback."""
    response = client.post("/health/boom")
    assert response.status_code == 500
    body = response.json()
    assert body["error"] == "internal_error"
    assert "Traceback" not in response.text


def test_openapi_schema_is_served(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert "/auth/login" in schema["paths"]
