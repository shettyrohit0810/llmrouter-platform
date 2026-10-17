"""Who may read a job: anonymous jobs by id, project jobs only by project members
or that project's API key; the job list is scoped to the caller's projects."""

import uuid

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app

TRAIN = {"router": "elorouter", "config_path": "configs/train/elorouter.yaml"}


@pytest.fixture()
def client():
    return TestClient(create_app())


def _login(client):
    email = f"test-{uuid.uuid4().hex}@example.com"
    client.post("/api/v1/auth/register", json={"email": email, "password": "hunter2hunter"})
    tokens = client.post(
        "/api/v1/auth/login", json={"email": email, "password": "hunter2hunter"}
    ).json()
    return email, {"Authorization": f"Bearer {tokens['access_token']}"}


def _project_with_key(client, headers):
    org = client.post(
        "/api/v1/orgs", json={"name": f"Org {uuid.uuid4().hex[:8]}"}, headers=headers
    ).json()
    project = client.post(
        f"/api/v1/orgs/{org['id']}/projects", json={"name": "P"}, headers=headers
    ).json()
    key = client.post(
        "/api/v1/api-keys", json={"name": "k", "project_id": project["id"]}, headers=headers
    ).json()
    return org, project, {"X-API-Key": key["api_key"]}


@pytest.mark.integration
def test_anonymous_job_is_readable_by_id(client):
    job_id = client.post("/api/v1/train", json=TRAIN).json()["job_id"]
    assert client.get(f"/api/v1/jobs/{job_id}").status_code == 200


@pytest.mark.integration
def test_project_job_needs_credentials(client):
    _, owner = _login(client)
    _, _, key = _project_with_key(client, owner)
    job_id = client.post("/api/v1/train", json=TRAIN, headers=key).json()["job_id"]

    assert client.get(f"/api/v1/jobs/{job_id}").status_code == 401
    assert client.get(f"/api/v1/jobs/{job_id}", headers=key).status_code == 200
    assert client.get(f"/api/v1/jobs/{job_id}", headers=owner).status_code == 200


@pytest.mark.integration
def test_other_tenants_cannot_read_a_project_job(client):
    _, owner = _login(client)
    _, _, key = _project_with_key(client, owner)
    job_id = client.post("/api/v1/train", json=TRAIN, headers=key).json()["job_id"]

    _, outsider = _login(client)
    _, _, other_key = _project_with_key(client, outsider)
    assert client.get(f"/api/v1/jobs/{job_id}", headers=outsider).status_code == 403
    assert client.get(f"/api/v1/jobs/{job_id}", headers=other_key).status_code == 403


@pytest.mark.integration
def test_viewer_member_can_read_a_project_job(client):
    _, owner = _login(client)
    viewer_email, viewer = _login(client)
    org, _, key = _project_with_key(client, owner)
    client.post(
        f"/api/v1/orgs/{org['id']}/members",
        json={"email": viewer_email, "role": "viewer"},
        headers=owner,
    )
    job_id = client.post("/api/v1/train", json=TRAIN, headers=key).json()["job_id"]
    assert client.get(f"/api/v1/jobs/{job_id}", headers=viewer).status_code == 200


@pytest.mark.integration
def test_job_list_requires_login_and_shows_only_own_projects(client):
    assert client.get("/api/v1/jobs").status_code == 422  # no Authorization header

    _, alice = _login(client)
    _, bob = _login(client)
    _, _, alice_key = _project_with_key(client, alice)
    alice_job = client.post("/api/v1/train", json=TRAIN, headers=alice_key).json()["job_id"]

    alice_ids = {j["job_id"] for j in client.get("/api/v1/jobs", headers=alice).json()["jobs"]}
    bob_ids = {j["job_id"] for j in client.get("/api/v1/jobs", headers=bob).json()["jobs"]}
    assert alice_job in alice_ids
    assert alice_job not in bob_ids


@pytest.mark.integration
def test_enqueueing_does_not_hold_a_second_connection(client, monkeypatch):
    """Regression: submitting a job used to keep the request session's pooled
    connection checked out while the job store opened another, which deadlocked
    the pool under concurrent requests (QueuePool limit ... timed out)."""
    from backend.api.services.jobs import PostgresJobStore
    from backend.db.session import get_engine

    seen = []
    real_create = PostgresJobStore.create

    def spy(self, *args, **kwargs):
        seen.append(get_engine().pool.checkedout())
        return real_create(self, *args, **kwargs)

    monkeypatch.setattr(PostgresJobStore, "create", spy)
    _, owner = _login(client)
    _, _, key = _project_with_key(client, owner)
    assert client.post("/api/v1/train", json=TRAIN, headers=key).status_code == 202
    assert seen == [0]
