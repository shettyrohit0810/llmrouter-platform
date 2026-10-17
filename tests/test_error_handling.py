from fastapi.testclient import TestClient

from backend.app import create_app


def test_404_returns_uniform_error_shape():
    client = TestClient(create_app())
    response = client.get("/api/v1/jobs/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert body["error_type"] == "http_error"
    assert "error" in body


def test_validation_error_returns_422_with_details():
    client = TestClient(create_app())
    response = client.post("/api/v1/route", json={"router": "knnrouter"})  # missing required fields
    assert response.status_code == 422
    body = response.json()
    assert body["error_type"] == "validation_error"


def test_unhandled_exception_never_leaks_traceback():
    client = TestClient(create_app(), raise_server_exceptions=False)
    response = client.post(
        "/api/v1/route",
        json={"router": "nonexistent_router_xyz", "config_path": "bad.yaml", "query": "test"},
    )
    assert response.status_code in (404, 500)
    body = response.json()
    assert "Traceback" not in str(body)
    assert 'File "' not in str(body)
