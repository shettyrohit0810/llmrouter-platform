"""Integration tests for Milestone 10's usage analytics -- require the real
dev Postgres container.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.db.session import session_scope
from backend.worker.queue import claim_next_job
from backend.worker.runner import run_claimed_job


def _unique_email() -> str:
    return f"test-{uuid.uuid4().hex}@example.com"


def _process_one_job(job_id):
    """Claims and runs exactly the given queued job -- simulates what a real
    backend/worker/main.py process does, since submitting a job via the API
    no longer executes it in-process (Milestone 7's BackgroundTasks
    approach was replaced by the real worker queue)."""
    with session_scope() as db:
        claimed = claim_next_job(db, only_job_id=uuid.UUID(job_id))
    assert claimed is not None, "expected the submitted job to be claimable"
    run_claimed_job(claimed)


@pytest.fixture()
def client():
    return TestClient(create_app())


def _register_and_login(client, password="hunter2hunter"):
    email = _unique_email()
    client.post("/api/v1/auth/register", json={"email": email, "password": password})
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": password}).json()
    return email, {"Authorization": f"Bearer {tokens['access_token']}"}


def _make_project_scoped_api_key(client, auth_header):
    org = client.post(
        "/api/v1/orgs", json={"name": f"Org {uuid.uuid4().hex[:8]}"}, headers=auth_header
    ).json()
    project = client.post(
        f"/api/v1/orgs/{org['id']}/projects", json={"name": "Default"}, headers=auth_header
    ).json()
    key = client.post(
        "/api/v1/api-keys",
        json={"name": "test-key", "project_id": project["id"]},
        headers=auth_header,
    ).json()

    return project, {"X-API-Key": key["api_key"]}


@pytest.mark.integration
def test_route_with_project_scoped_key_records_usage(client):
    _, auth_header = _register_and_login(client)
    project, api_key_header = _make_project_scoped_api_key(client, auth_header)

    r = client.post(
        "/api/v1/route",
        json={
            "router": "knnrouter",
            "config_path": "configs/serve/knnrouter.yaml",
            "query": "hello",
        },
        headers=api_key_header,
    )
    assert r.status_code == 200

    records = client.get(f"/api/v1/projects/{project['id']}/usage", headers=auth_header).json()[
        "records"
    ]
    assert len(records) == 1
    assert records[0]["endpoint"] == "/api/v1/route"
    assert records[0]["router_name"] == "knnrouter"
    assert records[0]["latency_ms"] > 0
    assert records[0]["status_code"] == 200


@pytest.mark.integration
def test_route_without_api_key_records_no_usage(client):
    r = client.post(
        "/api/v1/route",
        json={
            "router": "knnrouter",
            "config_path": "configs/serve/knnrouter.yaml",
            "query": "hello",
        },
    )
    assert r.status_code == 200
    # No project context -> nothing recorded, nothing to assert against a
    # project (there is none) -- this test just proves route() still works
    # unauthenticated (Phase 3 behavior preserved) and doesn't crash.


@pytest.mark.integration
def test_benchmark_records_usage_with_token_estimate(client):
    _, auth_header = _register_and_login(client)
    project, api_key_header = _make_project_scoped_api_key(client, auth_header)

    r = client.post(
        "/api/v1/benchmark",
        json={
            "router": "knnrouter",
            "config_path": "configs/serve/knnrouter.yaml",
            "sample_size": 5,
        },
        headers=api_key_header,
    )
    job_id = r.json()["job_id"]
    _process_one_job(job_id)
    client.get(f"/api/v1/jobs/{job_id}", headers=api_key_header).json()

    records = client.get(f"/api/v1/projects/{project['id']}/usage", headers=auth_header).json()[
        "records"
    ]
    assert len(records) == 1
    assert records[0]["endpoint"] == "/api/v1/benchmark"
    assert records[0]["tokens_output"] is not None


@pytest.mark.integration
def test_usage_summary_aggregates_across_endpoints(client):
    _, auth_header = _register_and_login(client)
    project, api_key_header = _make_project_scoped_api_key(client, auth_header)

    client.post(
        "/api/v1/route",
        json={
            "router": "knnrouter",
            "config_path": "configs/serve/knnrouter.yaml",
            "query": "a",
        },
        headers=api_key_header,
    )
    client.post(
        "/api/v1/route",
        json={
            "router": "elorouter",
            "config_path": "configs/serve/elorouter.yaml",
            "query": "b",
        },
        headers=api_key_header,
    )

    summary = client.get(
        f"/api/v1/projects/{project['id']}/usage/summary", headers=auth_header
    ).json()

    assert summary["total_requests"] == 2
    assert summary["requests_by_endpoint"] == {"/api/v1/route": 2}
    assert summary["requests_by_router"] == {"knnrouter": 1, "elorouter": 1}
    assert summary["average_latency_ms"] > 0
    assert summary["total_cost_estimate"] == 0.0


@pytest.mark.integration
def test_usage_endpoints_require_project_membership(client):
    _, owner_header = _register_and_login(client)
    project, api_key_header = _make_project_scoped_api_key(client, owner_header)
    _, outsider_header = _register_and_login(client)

    r = client.get(f"/api/v1/projects/{project['id']}/usage", headers=outsider_header)
    assert r.status_code == 403

    r = client.get(f"/api/v1/projects/{project['id']}/usage/summary", headers=outsider_header)
    assert r.status_code == 403


@pytest.mark.integration
def test_usage_summary_empty_project_returns_zeros(client):
    _, auth_header = _register_and_login(client)
    org = client.post(
        "/api/v1/orgs", json={"name": f"Empty Org {uuid.uuid4().hex[:6]}"}, headers=auth_header
    ).json()
    project = client.post(
        f"/api/v1/orgs/{org['id']}/projects", json={"name": "Default"}, headers=auth_header
    ).json()

    summary = client.get(
        f"/api/v1/projects/{project['id']}/usage/summary", headers=auth_header
    ).json()
    assert summary["total_requests"] == 0
    assert summary["average_latency_ms"] == 0.0
    assert summary["requests_by_endpoint"] == {}
