"""Project-scoped API key creation: who may create one, and what it records."""

import uuid

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app


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


def _org_and_project(client, headers):
    org = client.post(
        "/api/v1/orgs", json={"name": f"Org {uuid.uuid4().hex[:8]}"}, headers=headers
    ).json()
    project = client.post(
        f"/api/v1/orgs/{org['id']}/projects", json={"name": "Default"}, headers=headers
    ).json()
    return org, project


@pytest.mark.integration
def test_owner_can_create_a_project_scoped_key(client):
    _, owner = _login(client)
    _, project = _org_and_project(client, owner)

    r = client.post(
        "/api/v1/api-keys", json={"name": "ci", "project_id": project["id"]}, headers=owner
    )
    assert r.status_code == 201
    assert r.json()["project_id"] == project["id"]

    listed = client.get("/api/v1/api-keys", headers=owner).json()["api_keys"]
    assert any(k["project_id"] == project["id"] for k in listed)


@pytest.mark.integration
def test_key_without_project_id_stays_unscoped(client):
    _, owner = _login(client)
    r = client.post("/api/v1/api-keys", json={"name": "plain"}, headers=owner)
    assert r.status_code == 201
    assert r.json()["project_id"] is None


@pytest.mark.integration
def test_viewer_cannot_create_a_key_for_the_project(client):
    _, owner = _login(client)
    viewer_email, viewer = _login(client)
    org, project = _org_and_project(client, owner)
    client.post(
        f"/api/v1/orgs/{org['id']}/members",
        json={"email": viewer_email, "role": "viewer"},
        headers=owner,
    )

    r = client.post(
        "/api/v1/api-keys", json={"name": "x", "project_id": project["id"]}, headers=viewer
    )
    assert r.status_code == 403


@pytest.mark.integration
def test_non_member_cannot_create_a_key_for_the_project(client):
    _, owner = _login(client)
    _, outsider = _login(client)
    _, project = _org_and_project(client, owner)

    r = client.post(
        "/api/v1/api-keys", json={"name": "x", "project_id": project["id"]}, headers=outsider
    )
    assert r.status_code == 403


@pytest.mark.integration
def test_unknown_project_is_404(client):
    _, owner = _login(client)
    r = client.post(
        "/api/v1/api-keys", json={"name": "x", "project_id": str(uuid.uuid4())}, headers=owner
    )
    assert r.status_code == 404
