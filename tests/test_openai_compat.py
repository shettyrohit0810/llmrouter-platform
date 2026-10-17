"""Confirms the mounted gateway surface (/v1/*) works, and that the backend's
own /health takes precedence over the gateway's /health."""

from fastapi.testclient import TestClient

from backend.app import create_app


def test_mounted_v1_models_reachable():
    client = TestClient(create_app())
    response = client.get("/v1/models")
    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "list"
    assert len(body["data"]) > 0


def test_root_health_is_backends_not_the_gateways():
    # The gateway app also defines /health, but returns {"status", "strategy",
    # "llms"}; the backend's own minimal {"status": "ok"} must win because it
    # is registered before the gateway is mounted.
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
