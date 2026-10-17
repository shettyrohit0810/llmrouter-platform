"""Integration tests for Milestone 9's model registry -- require the real
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
def test_list_routers_syncs_from_cli_registry(client):
    _, auth_header = _register_and_login(client)
    r = client.get("/api/v1/registry/routers", headers=auth_header)
    assert r.status_code == 200
    names = {row["name"] for row in r.json()["routers"]}
    assert "knnrouter" in names
    assert "elorouter" in names


@pytest.mark.integration
def test_list_models_syncs_from_llm_candidates(client):
    _, auth_header = _register_and_login(client)
    r = client.get("/api/v1/registry/models", headers=auth_header)
    assert r.status_code == 200
    assert len(r.json()["models"]) > 0


@pytest.mark.integration
def test_registry_requires_authentication(client):
    r = client.get("/api/v1/registry/routers")
    assert r.status_code == 422  # missing required Authorization header


@pytest.mark.integration
def test_train_registers_router_version_and_training_job_detail(client):
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

    versions = client.get(
        "/api/v1/registry/router-versions",
        params={"router_name": "elorouter"},
        headers=auth_header,
    ).json()["versions"]
    assert len(versions) >= 1
    version = versions[0]
    assert version["checkpoint_path"] == "saved_models/elorouter/elorouter.pkl"
    assert version["training_job_id"] == job_id
    assert version["project_id"] == project["id"]
    assert version["status"] == "active"

    # The train experiment's router_version links back to this same version.
    experiment = client.get(
        f"/api/v1/experiments/{job['experiment_id']}", headers=auth_header
    ).json()
    assert experiment["router_version"] == version["id"]


@pytest.mark.integration
def test_get_router_version_by_id(client):
    _, auth_header = _register_and_login(client)
    project, api_key_header = _make_project_scoped_api_key(client, auth_header)

    r = client.post(
        "/api/v1/train",
        json={"router": "elorouter", "config_path": "configs/train/elorouter.yaml"},
        headers=api_key_header,
    )
    _process_one_job(r.json()["job_id"])
    versions = client.get(
        "/api/v1/registry/router-versions",
        params={"router_name": "elorouter"},
        headers=auth_header,
    ).json()["versions"]
    version_id = versions[0]["id"]

    r = client.get(f"/api/v1/registry/router-versions/{version_id}", headers=auth_header)
    assert r.status_code == 200
    assert r.json()["id"] == version_id


@pytest.mark.integration
def test_get_unknown_router_version_returns_404(client):
    _, auth_header = _register_and_login(client)
    r = client.get(f"/api/v1/registry/router-versions/{uuid.uuid4()}", headers=auth_header)
    assert r.status_code == 404


@pytest.mark.integration
def test_manually_register_router_version_without_project(client):
    _, auth_header = _register_and_login(client)
    r = client.post(
        "/api/v1/registry/router-versions",
        json={
            "router_name": "knnrouter",
            "version_label": "manual-v1",
            "checkpoint_path": "saved_models/knnrouter/manual.pkl",
        },
        headers=auth_header,
    )
    assert r.status_code == 201
    assert r.json()["version_label"] == "manual-v1"
    assert r.json()["project_id"] is None


@pytest.mark.integration
def test_register_project_scoped_version_requires_developer_role(client):
    _, owner_header = _register_and_login(client)
    email_viewer, headers_viewer = _register_and_login(client)
    org = client.post(
        "/api/v1/orgs", json={"name": f"RegRole Org {uuid.uuid4().hex[:6]}"}, headers=owner_header
    ).json()
    project = client.post(
        f"/api/v1/orgs/{org['id']}/projects", json={"name": "Default"}, headers=owner_header
    ).json()
    client.post(
        f"/api/v1/orgs/{org['id']}/members",
        json={"email": email_viewer, "role": "viewer"},
        headers=owner_header,
    )

    r = client.post(
        "/api/v1/registry/router-versions",
        json={
            "router_name": "knnrouter",
            "version_label": "v1",
            "checkpoint_path": "saved_models/knnrouter/knnrouter.pkl",
            "project_id": project["id"],
        },
        headers=headers_viewer,
    )
    assert r.status_code == 403

    r = client.post(
        "/api/v1/registry/router-versions",
        json={
            "router_name": "knnrouter",
            "version_label": "v1",
            "checkpoint_path": "saved_models/knnrouter/knnrouter.pkl",
            "project_id": project["id"],
        },
        headers=owner_header,
    )
    assert r.status_code == 201


@pytest.mark.integration
def test_archive_router_version_requires_admin_role(client):
    _, owner_header = _register_and_login(client)
    email_dev, headers_dev = _register_and_login(client)
    org = client.post(
        "/api/v1/orgs", json={"name": f"Archive Org {uuid.uuid4().hex[:6]}"}, headers=owner_header
    ).json()
    project = client.post(
        f"/api/v1/orgs/{org['id']}/projects", json={"name": "Default"}, headers=owner_header
    ).json()
    client.post(
        f"/api/v1/orgs/{org['id']}/members",
        json={"email": email_dev, "role": "developer"},
        headers=owner_header,
    )
    created = client.post(
        "/api/v1/registry/router-versions",
        json={
            "router_name": "knnrouter",
            "version_label": "v1",
            "checkpoint_path": "saved_models/knnrouter/knnrouter.pkl",
            "project_id": project["id"],
        },
        headers=owner_header,
    ).json()

    r = client.post(
        f"/api/v1/registry/router-versions/{created['id']}/archive", headers=headers_dev
    )
    assert r.status_code == 403

    r = client.post(
        f"/api/v1/registry/router-versions/{created['id']}/archive", headers=owner_header
    )
    assert r.status_code == 200
    assert r.json()["status"] == "archived"
