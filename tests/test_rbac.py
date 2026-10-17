"""Integration tests for organizations/projects/RBAC -- require the local dev
Postgres container, same convention as tests/backend/test_auth.py."""

import uuid

import pytest
from fastapi.testclient import TestClient

from backend.api.rbac.service import _slugify
from backend.app import create_app


def _unique_email() -> str:
    return f"test-{uuid.uuid4().hex}@example.com"


def _unique_org_name(base: str) -> str:
    # Organization slugs are globally unique and this suite runs against a
    # persistent dev database (not rolled back between runs, unlike users
    # which already use unique-per-test emails) -- a fixed name like "Acme
    # Corp" would collide with whatever a previous run already created,
    # making slug-collision-count assertions depend on test history.
    return f"{base} {uuid.uuid4().hex[:8]}"


@pytest.fixture()
def client():
    return TestClient(create_app())


def _register_and_login(client, email=None, password="hunter2hunter"):
    email = email or _unique_email()
    client.post("/api/v1/auth/register", json={"email": email, "password": password})
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": password}).json()
    return email, {"Authorization": f"Bearer {tokens['access_token']}"}


@pytest.mark.integration
def test_create_organization_makes_creator_owner(client):
    _, headers = _register_and_login(client)
    name = _unique_org_name("Acme Corp")
    r = client.post("/api/v1/orgs", json={"name": name}, headers=headers)
    assert r.status_code == 201
    org = r.json()
    assert org["slug"] == _slugify(name)
    assert org["plan"] == "free"

    r = client.get(f"/api/v1/orgs/{org['id']}/members", headers=headers)
    assert r.status_code == 200
    members = r.json()["members"]
    assert len(members) == 1
    assert members[0]["role"] == "owner"


@pytest.mark.integration
def test_organization_slug_is_unique_per_name_collision(client):
    _, headers = _register_and_login(client)
    name = _unique_org_name("Dup Co")
    r1 = client.post("/api/v1/orgs", json={"name": name}, headers=headers)
    r2 = client.post("/api/v1/orgs", json={"name": name}, headers=headers)
    base_slug = _slugify(name)
    assert r1.json()["slug"] == base_slug
    assert r2.json()["slug"] == f"{base_slug}-2"


@pytest.mark.integration
def test_list_organizations_only_shows_own_orgs(client):
    _, headers_a = _register_and_login(client)
    _, headers_b = _register_and_login(client)
    client.post("/api/v1/orgs", json={"name": "A Org"}, headers=headers_a)

    r = client.get("/api/v1/orgs", headers=headers_b)
    assert r.status_code == 200
    assert r.json()["organizations"] == []


@pytest.mark.integration
def test_non_member_gets_403_on_organization_detail(client):
    _, headers_a = _register_and_login(client)
    _, headers_b = _register_and_login(client)
    org = client.post("/api/v1/orgs", json={"name": "Private Org"}, headers=headers_a).json()

    r = client.get(f"/api/v1/orgs/{org['id']}", headers=headers_b)
    assert r.status_code == 403


@pytest.mark.integration
def test_unknown_organization_returns_404(client):
    _, headers = _register_and_login(client)
    r = client.get(f"/api/v1/orgs/{uuid.uuid4()}", headers=headers)
    assert r.status_code == 404


@pytest.mark.integration
def test_add_member_requires_admin_role(client):
    _, headers_owner = _register_and_login(client)
    email_viewer, headers_viewer = _register_and_login(client)
    email_new, _ = _register_and_login(client)
    org = client.post("/api/v1/orgs", json={"name": "Role Test Org"}, headers=headers_owner).json()

    # Owner adds the viewer.
    r = client.post(
        f"/api/v1/orgs/{org['id']}/members",
        json={"email": email_viewer, "role": "viewer"},
        headers=headers_owner,
    )
    assert r.status_code == 201

    # Viewer cannot add members (requires admin+).
    r = client.post(
        f"/api/v1/orgs/{org['id']}/members",
        json={"email": email_new, "role": "viewer"},
        headers=headers_viewer,
    )
    assert r.status_code == 403


@pytest.mark.integration
def test_add_member_unknown_email_returns_404(client):
    _, headers = _register_and_login(client)
    org = client.post("/api/v1/orgs", json={"name": "Org X"}, headers=headers).json()
    r = client.post(
        f"/api/v1/orgs/{org['id']}/members",
        json={"email": _unique_email(), "role": "viewer"},
        headers=headers,
    )
    assert r.status_code == 404


@pytest.mark.integration
def test_only_owner_can_change_roles(client):
    _, headers_owner = _register_and_login(client)
    email_admin, headers_admin = _register_and_login(client)
    org = client.post(
        "/api/v1/orgs", json={"name": "Change Role Org"}, headers=headers_owner
    ).json()
    client.post(
        f"/api/v1/orgs/{org['id']}/members",
        json={"email": email_admin, "role": "admin"},
        headers=headers_owner,
    )

    # Admin cannot promote themselves or anyone else to owner-level change (requires owner).
    admin_id = _member_user_id(client, org["id"], headers_owner, email_admin)
    r = client.patch(
        f"/api/v1/orgs/{org['id']}/members/{admin_id}",
        json={"role": "developer"},
        headers=headers_admin,
    )
    assert r.status_code == 403

    # Owner can.
    target_id = _member_user_id(client, org["id"], headers_owner, email_admin)
    r = client.patch(
        f"/api/v1/orgs/{org['id']}/members/{target_id}",
        json={"role": "developer"},
        headers=headers_owner,
    )
    assert r.status_code == 200
    assert r.json()["role"] == "developer"


def _member_user_id(client, org_id, headers, email):
    members = client.get(f"/api/v1/orgs/{org_id}/members", headers=headers).json()["members"]
    return next(m["user_id"] for m in members if m["email"] == email)


@pytest.mark.integration
def test_cannot_demote_last_owner(client):
    _, headers_owner = _register_and_login(client)
    org = client.post("/api/v1/orgs", json={"name": "Solo Owner Org"}, headers=headers_owner).json()
    owner_id = _member_user_id(
        client, org["id"], headers_owner, _current_email(client, headers_owner)
    )

    r = client.patch(
        f"/api/v1/orgs/{org['id']}/members/{owner_id}",
        json={"role": "admin"},
        headers=headers_owner,
    )
    assert r.status_code == 409


def _current_email(client, headers):
    return client.get("/api/v1/auth/me", headers=headers).json()["email"]


@pytest.mark.integration
def test_cannot_remove_last_owner(client):
    _, headers_owner = _register_and_login(client)
    org = client.post(
        "/api/v1/orgs", json={"name": "Solo Owner Org 2"}, headers=headers_owner
    ).json()
    owner_id = _member_user_id(
        client, org["id"], headers_owner, _current_email(client, headers_owner)
    )

    r = client.delete(f"/api/v1/orgs/{org['id']}/members/{owner_id}", headers=headers_owner)
    assert r.status_code == 409


@pytest.mark.integration
def test_remove_member_requires_admin(client):
    _, headers_owner = _register_and_login(client)
    email_viewer, headers_viewer = _register_and_login(client)
    org = client.post(
        "/api/v1/orgs", json={"name": "Remove Test Org"}, headers=headers_owner
    ).json()
    client.post(
        f"/api/v1/orgs/{org['id']}/members",
        json={"email": email_viewer, "role": "viewer"},
        headers=headers_owner,
    )
    viewer_id = _member_user_id(client, org["id"], headers_owner, email_viewer)

    # Viewer cannot remove themselves (requires admin+).
    r = client.delete(f"/api/v1/orgs/{org['id']}/members/{viewer_id}", headers=headers_viewer)
    assert r.status_code == 403

    r = client.delete(f"/api/v1/orgs/{org['id']}/members/{viewer_id}", headers=headers_owner)
    assert r.status_code == 204


@pytest.mark.integration
def test_create_project_requires_developer_role(client):
    _, headers_owner = _register_and_login(client)
    email_viewer, headers_viewer = _register_and_login(client)
    org = client.post("/api/v1/orgs", json={"name": "Project Org"}, headers=headers_owner).json()
    client.post(
        f"/api/v1/orgs/{org['id']}/members",
        json={"email": email_viewer, "role": "viewer"},
        headers=headers_owner,
    )

    r = client.post(
        f"/api/v1/orgs/{org['id']}/projects",
        json={"name": "Widget Service"},
        headers=headers_viewer,
    )
    assert r.status_code == 403

    r = client.post(
        f"/api/v1/orgs/{org['id']}/projects", json={"name": "Widget Service"}, headers=headers_owner
    )
    assert r.status_code == 201
    assert r.json()["slug"] == "widget-service"


@pytest.mark.integration
def test_project_visible_to_any_org_member_not_others(client):
    _, headers_owner = _register_and_login(client)
    _, headers_outsider = _register_and_login(client)
    org = client.post("/api/v1/orgs", json={"name": "Visible Org"}, headers=headers_owner).json()
    project = client.post(
        f"/api/v1/orgs/{org['id']}/projects", json={"name": "Core"}, headers=headers_owner
    ).json()

    r = client.get(f"/api/v1/projects/{project['id']}", headers=headers_owner)
    assert r.status_code == 200

    r = client.get(f"/api/v1/projects/{project['id']}", headers=headers_outsider)
    assert r.status_code == 403


@pytest.mark.integration
def test_delete_project_requires_admin_role(client):
    _, headers_owner = _register_and_login(client)
    email_dev, headers_dev = _register_and_login(client)
    org = client.post(
        "/api/v1/orgs", json={"name": "Delete Proj Org"}, headers=headers_owner
    ).json()
    client.post(
        f"/api/v1/orgs/{org['id']}/members",
        json={"email": email_dev, "role": "developer"},
        headers=headers_owner,
    )
    project = client.post(
        f"/api/v1/orgs/{org['id']}/projects", json={"name": "Deletable"}, headers=headers_owner
    ).json()

    r = client.delete(f"/api/v1/projects/{project['id']}", headers=headers_dev)
    assert r.status_code == 403

    r = client.delete(f"/api/v1/projects/{project['id']}", headers=headers_owner)
    assert r.status_code == 204

    r = client.get(f"/api/v1/projects/{project['id']}", headers=headers_owner)
    assert r.status_code == 404
