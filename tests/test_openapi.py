"""Confirms the unified OpenAPI schema covers every /api/v1/* + /health path,
and that both Swagger and ReDoc serve."""

from fastapi.testclient import TestClient

from backend.app import create_app

EXPECTED_PATHS = {
    "/health",
    "/api/v1/routers",
    "/api/v1/models",
    "/api/v1/route",
    "/api/v1/infer",
    "/api/v1/train",
    "/api/v1/benchmark",
    "/api/v1/benchmark/compare",
    "/api/v1/jobs/{job_id}",
    "/api/v1/jobs",
}


def test_openapi_schema_covers_all_management_paths():
    client = TestClient(create_app())
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert EXPECTED_PATHS.issubset(set(schema["paths"].keys()))


def test_swagger_docs_serves():
    client = TestClient(create_app())
    response = client.get("/docs")
    assert response.status_code == 200
    assert "swagger" in response.text.lower()


def test_redoc_serves():
    client = TestClient(create_app())
    response = client.get("/redoc")
    assert response.status_code == 200
    assert "redoc" in response.text.lower()
