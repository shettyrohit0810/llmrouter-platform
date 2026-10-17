"""Integration tests for Milestone 12's observability (Prometheus metrics +
OpenTelemetry tracing) -- require the real dev Postgres/Redis containers.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app


def _unique_email() -> str:
    return f"test-{uuid.uuid4().hex}@example.com"


@pytest.fixture()
def client():
    return TestClient(create_app())


@pytest.mark.integration
def test_metrics_endpoint_returns_prometheus_text_format(client):
    r = client.get("/metrics")
    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]


@pytest.mark.integration
def test_metrics_records_http_requests(client):
    client.get("/health")

    r = client.get("/metrics")
    body = r.text
    assert "http_requests_total{" in body
    # The route *template* is what should appear, not a raw path -- there's
    # no path parameter on /health to worry about, but this confirms the
    # counter is actually being incremented, not just registered.
    assert 'path="/health"' in body


@pytest.mark.integration
def test_metrics_uses_route_template_not_raw_path(client):
    email, password = _unique_email(), "hunter2hunter"
    client.post("/api/v1/auth/register", json={"email": email, "password": password})
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": password}).json()
    auth_header = {"Authorization": f"Bearer {tokens['access_token']}"}
    org = client.post(
        "/api/v1/orgs", json={"name": f"Org {uuid.uuid4().hex[:8]}"}, headers=auth_header
    ).json()

    client.get(f"/api/v1/orgs/{org['id']}", headers=auth_header)

    body = client.get("/metrics").text
    # The route template, with the literal path parameter name -- not the
    # raw org UUID, which would give every organization its own unbounded
    # Prometheus time series. Note: route.path is relative to the
    # APIRouter it was defined on ("/orgs/{organization_id}"), not the
    # fully composed path -- the "/api/v1" prefix is applied by router
    # nesting, not baked into each route's own .path string.
    assert 'path="/orgs/{organization_id}"' in body
    assert org["id"] not in body


@pytest.mark.integration
def test_job_submission_increments_job_metric(client):
    before = client.get("/metrics").text
    before_count = _extract_counter(before, "job_submissions_total", 'job_type="train"')

    client.post(
        "/api/v1/train",
        json={"router": "knnrouter", "config_path": "configs/train/knnrouter.yaml"},
    )

    after = client.get("/metrics").text
    after_count = _extract_counter(after, "job_submissions_total", 'job_type="train"')
    assert after_count == before_count + 1


def _extract_counter(prometheus_text: str, metric_name: str, label_fragment: str) -> float:
    for line in prometheus_text.splitlines():
        if line.startswith(metric_name) and label_fragment in line:
            return float(line.rsplit(" ", 1)[-1])
    return 0.0
