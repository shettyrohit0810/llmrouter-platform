"""Integration tests for experiment tracking -- require the real dev Postgres
container. Tests that need attribution use a project-scoped API key."""

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
    """Creates an org + project + an API key scoped to that project."""
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
def test_benchmark_with_project_scoped_key_creates_experiment(client):
    _, auth_header = _register_and_login(client)
    project, api_key_header = _make_project_scoped_api_key(client, auth_header)

    r = client.post(
        "/api/v1/benchmark",
        json={
            "router": "knnrouter",
            "config_path": "configs/serve/knnrouter.yaml",
            # Capped: the test's objective is "does this create an Experiment
            # record", not "benchmark real accuracy" -- the default dataset
            # has hundreds of queries, and real route_single() calls across
            # all of them (x2 routers in the compare test below) turned out
            # to run for over an hour, the same class of runaway-test-runtime
            # issue Phase 2 hit with DCRouter's full training test.
            "sample_size": 5,
            "create_experiment": True,
        },
        headers=api_key_header,
    )
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    _process_one_job(job_id)

    job = client.get(f"/api/v1/jobs/{job_id}", headers=api_key_header).json()
    assert job["status"] == "completed"
    assert job["experiment_id"] is not None

    listing = client.get(
        f"/api/v1/projects/{project['id']}/experiments", headers=auth_header
    ).json()
    assert len(listing["experiments"]) == 1
    experiment = listing["experiments"][0]
    assert experiment["id"] == job["experiment_id"]
    assert experiment["experiment_type"] == "benchmark"
    assert experiment["router_name"] == "knnrouter"
    assert experiment["duration_seconds"] is not None
    assert experiment["metrics"] is not None

    detail = client.get(f"/api/v1/experiments/{experiment['id']}", headers=auth_header).json()
    assert detail["id"] == experiment["id"]


@pytest.mark.integration
def test_benchmark_create_experiment_false_creates_no_experiment(client):
    _, auth_header = _register_and_login(client)
    project, api_key_header = _make_project_scoped_api_key(client, auth_header)

    r = client.post(
        "/api/v1/benchmark",
        json={
            "router": "knnrouter",
            "config_path": "configs/serve/knnrouter.yaml",
            "sample_size": 5,
            "create_experiment": False,
        },
        headers=api_key_header,
    )
    job_id = r.json()["job_id"]
    _process_one_job(job_id)
    job = client.get(f"/api/v1/jobs/{job_id}", headers=api_key_header).json()

    assert job["status"] == "completed"
    assert job["experiment_id"] is None

    listing = client.get(
        f"/api/v1/projects/{project['id']}/experiments", headers=auth_header
    ).json()
    assert listing["experiments"] == []


@pytest.mark.integration
def test_benchmark_without_api_key_creates_no_experiment(client):
    """create_experiment defaults to True, but with no resolvable project
    context (anonymous call, no X-API-Key), no experiment can be attached --
    the flag is silently ignored rather than erroring."""
    r = client.post(
        "/api/v1/benchmark",
        json={
            "router": "knnrouter",
            "config_path": "configs/serve/knnrouter.yaml",
            "sample_size": 5,
        },
    )
    job_id = r.json()["job_id"]
    _process_one_job(job_id)
    job = client.get(f"/api/v1/jobs/{job_id}").json()
    assert job["experiment_id"] is None


@pytest.mark.integration
def test_train_with_project_scoped_key_creates_experiment(client):
    _, auth_header = _register_and_login(client)
    project, api_key_header = _make_project_scoped_api_key(client, auth_header)

    r = client.post(
        "/api/v1/train",
        json={
            "router": "elorouter",
            "config_path": "configs/train/elorouter.yaml",
            "create_experiment": True,
        },
        headers=api_key_header,
    )
    job_id = r.json()["job_id"]
    _process_one_job(job_id)
    job = client.get(f"/api/v1/jobs/{job_id}", headers=api_key_header).json()

    assert job["status"] == "completed"
    assert job["experiment_id"] is not None

    listing = client.get(
        f"/api/v1/projects/{project['id']}/experiments", headers=auth_header
    ).json()
    experiment = listing["experiments"][0]
    assert experiment["experiment_type"] == "train"
    assert experiment["router_name"] == "elorouter"
    assert experiment["metadata"]["device"] == "cpu"


@pytest.mark.integration
def test_benchmark_compare_with_project_scoped_key_creates_experiment(client):
    _, auth_header = _register_and_login(client)
    project, api_key_header = _make_project_scoped_api_key(client, auth_header)

    r = client.post(
        "/api/v1/benchmark/compare",
        json={
            "routers": ["knnrouter", "elorouter"],
            "config_paths": {
                "knnrouter": "configs/serve/knnrouter.yaml",
                "elorouter": "configs/serve/elorouter.yaml",
            },
            "sample_size": 5,
            "create_experiment": True,
        },
        headers=api_key_header,
    )
    job_id = r.json()["job_id"]
    _process_one_job(job_id)
    job = client.get(f"/api/v1/jobs/{job_id}", headers=api_key_header).json()

    assert job["status"] == "completed"
    assert job["experiment_id"] is not None

    listing = client.get(
        f"/api/v1/projects/{project['id']}/experiments", headers=auth_header
    ).json()
    experiment = listing["experiments"][0]
    assert experiment["experiment_type"] == "benchmark_compare"
    assert "ranking" in experiment["metrics"]


@pytest.mark.integration
def test_infer_defaults_to_no_experiment(client):
    _, auth_header = _register_and_login(client)
    _, api_key_header = _make_project_scoped_api_key(client, auth_header)

    r = client.post(
        "/api/v1/infer",
        json={
            "router": "knnrouter",
            "config_path": "configs/serve/knnrouter.yaml",
            "query": "hello",
        },
        headers=api_key_header,
    )
    assert r.json()["experiment_id"] is None


@pytest.mark.integration
def test_infer_with_project_scoped_key_and_flag_creates_experiment(client):
    _, auth_header = _register_and_login(client)
    project, api_key_header = _make_project_scoped_api_key(client, auth_header)

    r = client.post(
        "/api/v1/infer",
        json={
            "router": "knnrouter",
            "config_path": "configs/serve/knnrouter.yaml",
            "query": "hello",
            "create_experiment": True,
        },
        headers=api_key_header,
    )
    assert r.json()["experiment_id"] is not None

    listing = client.get(
        f"/api/v1/projects/{project['id']}/experiments", headers=auth_header
    ).json()
    assert len(listing["experiments"]) == 1
    assert listing["experiments"][0]["experiment_type"] == "infer"


@pytest.mark.integration
def test_experiment_list_requires_project_membership(client):
    _, owner_header = _register_and_login(client)
    project, api_key_header = _make_project_scoped_api_key(client, owner_header)
    _, outsider_header = _register_and_login(client)

    r = client.get(f"/api/v1/projects/{project['id']}/experiments", headers=outsider_header)
    assert r.status_code == 403


@pytest.mark.integration
def test_get_experiment_requires_org_membership(client):
    _, owner_header = _register_and_login(client)
    project, api_key_header = _make_project_scoped_api_key(client, owner_header)
    r = client.post(
        "/api/v1/benchmark",
        json={
            "router": "knnrouter",
            "config_path": "configs/serve/knnrouter.yaml",
            "sample_size": 5,
            "create_experiment": True,
        },
        headers=api_key_header,
    )
    _process_one_job(r.json()["job_id"])
    listing = client.get(
        f"/api/v1/projects/{project['id']}/experiments", headers=owner_header
    ).json()
    experiment_id = listing["experiments"][0]["id"]

    _, outsider_header = _register_and_login(client)
    r = client.get(f"/api/v1/experiments/{experiment_id}", headers=outsider_header)
    assert r.status_code == 403


@pytest.mark.integration
def test_get_unknown_experiment_returns_404(client):
    _, auth_header = _register_and_login(client)
    r = client.get(f"/api/v1/experiments/{uuid.uuid4()}", headers=auth_header)
    assert r.status_code == 404
