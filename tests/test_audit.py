"""Integration tests for Milestone 11's audit logging -- require the real
dev Postgres container.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.db.models.audit import AuditLog
from backend.db.models.user import User
from backend.db.session import session_scope


def _unique_email() -> str:
    return f"test-{uuid.uuid4().hex}@example.com"


@pytest.fixture()
def client():
    return TestClient(create_app())


def _register_and_login(client, password="hunter2hunter"):
    email = _unique_email()
    client.post("/api/v1/auth/register", json={"email": email, "password": password})
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": password}).json()
    return email, {"Authorization": f"Bearer {tokens['access_token']}"}


def _actions_for_email(email):
    with session_scope() as db:
        user = db.query(User).filter(User.email == email).first()
        assert user is not None
        return [log.action for log in db.query(AuditLog).filter(AuditLog.user_id == user.id).all()]


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

    return org, project, {"X-API-Key": key["api_key"]}


@pytest.mark.integration
def test_register_and_login_are_audited(client):
    email, _ = _register_and_login(client)
    actions = _actions_for_email(email)
    assert "auth.register" in actions
    assert "auth.login" in actions


@pytest.mark.integration
def test_failed_login_is_audited(client):
    email, _ = _register_and_login(client)
    client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-password"})

    with session_scope() as db:
        last = (
            db.query(AuditLog)
            .filter(AuditLog.action == "auth.login_failed")
            .order_by(AuditLog.created_at.desc())
            .first()
        )
        assert last is not None
        metadata_, user_id = last.metadata_, last.user_id
    assert metadata_["email"] == email
    assert metadata_["reason"] == "invalid_credentials"
    # No resolvable user for a failed login attempt.
    assert user_id is None


@pytest.mark.integration
def test_logout_is_audited(client):
    email, _ = _register_and_login(client)
    tokens = client.post(
        "/api/v1/auth/login", json={"email": email, "password": "hunter2hunter"}
    ).json()
    r = client.post("/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 204

    actions = _actions_for_email(email)
    assert "auth.logout" in actions


@pytest.mark.integration
def test_api_key_lifecycle_is_audited(client):
    _, auth_header = _register_and_login(client)
    key = client.post("/api/v1/api-keys", json={"name": "k1"}, headers=auth_header).json()
    client.delete(f"/api/v1/api-keys/{key['id']}", headers=auth_header)

    # API keys aren't organization-scoped, so there's no org to list these
    # through GET /orgs/{id}/audit-logs -- check the table directly instead.
    with session_scope() as db:
        rows = (
            db.query(AuditLog)
            .filter(AuditLog.resource_type == "api_key", AuditLog.resource_id == key["id"])
            .order_by(AuditLog.created_at)
            .all()
        )
        actions = [r.action for r in rows]
    assert actions == ["api_key.created", "api_key.revoked"]


@pytest.mark.integration
def test_org_and_project_lifecycle_is_audited(client):
    _, auth_header = _register_and_login(client)
    org = client.post(
        "/api/v1/orgs", json={"name": f"Org {uuid.uuid4().hex[:8]}"}, headers=auth_header
    ).json()
    project = client.post(
        f"/api/v1/orgs/{org['id']}/projects", json={"name": "Default"}, headers=auth_header
    ).json()
    r = client.delete(f"/api/v1/projects/{project['id']}", headers=auth_header)
    assert r.status_code == 204

    logs = client.get(f"/api/v1/orgs/{org['id']}/audit-logs", headers=auth_header).json()["logs"]
    actions = [log["action"] for log in logs]
    assert "org.created" in actions
    assert "project.created" in actions
    assert "project.deleted" in actions


@pytest.mark.integration
def test_member_role_changes_are_audited(client):
    _, owner_header = _register_and_login(client)
    member_email, _ = _register_and_login(client)
    org = client.post(
        "/api/v1/orgs", json={"name": f"Org {uuid.uuid4().hex[:8]}"}, headers=owner_header
    ).json()

    client.post(
        f"/api/v1/orgs/{org['id']}/members",
        json={"email": member_email, "role": "viewer"},
        headers=owner_header,
    )
    with session_scope() as db:
        member_id = str(db.query(User).filter(User.email == member_email).first().id)

    client.patch(
        f"/api/v1/orgs/{org['id']}/members/{member_id}",
        json={"role": "developer"},
        headers=owner_header,
    )
    client.delete(f"/api/v1/orgs/{org['id']}/members/{member_id}", headers=owner_header)

    logs = client.get(f"/api/v1/orgs/{org['id']}/audit-logs", headers=owner_header).json()["logs"]
    actions = [log["action"] for log in logs]
    assert "org.member_added" in actions
    assert "org.member_role_changed" in actions
    assert "org.member_removed" in actions


@pytest.mark.integration
def test_train_job_submission_is_audited(client):
    _, auth_header = _register_and_login(client)
    org, _project, api_key_header = _make_project_scoped_api_key(client, auth_header)

    client.post(
        "/api/v1/train",
        json={"router": "knnrouter", "config_path": "configs/train/knnrouter.yaml"},
        headers=api_key_header,
    )

    logs = client.get(f"/api/v1/orgs/{org['id']}/audit-logs", headers=auth_header).json()["logs"]
    actions = [log["action"] for log in logs]
    assert "job.train_submitted" in actions


@pytest.mark.integration
def test_audit_logs_require_admin_role(client):
    _, owner_header = _register_and_login(client)
    viewer_email, viewer_header = _register_and_login(client)
    org = client.post(
        "/api/v1/orgs", json={"name": f"Org {uuid.uuid4().hex[:8]}"}, headers=owner_header
    ).json()
    client.post(
        f"/api/v1/orgs/{org['id']}/members",
        json={"email": viewer_email, "role": "viewer"},
        headers=owner_header,
    )

    r = client.get(f"/api/v1/orgs/{org['id']}/audit-logs", headers=viewer_header)
    assert r.status_code == 403

    r = client.get(f"/api/v1/orgs/{org['id']}/audit-logs", headers=owner_header)
    assert r.status_code == 200


@pytest.mark.integration
def test_audit_logs_filter_by_action(client):
    _, auth_header = _register_and_login(client)
    org = client.post(
        "/api/v1/orgs", json={"name": f"Org {uuid.uuid4().hex[:8]}"}, headers=auth_header
    ).json()
    client.post(f"/api/v1/orgs/{org['id']}/projects", json={"name": "P1"}, headers=auth_header)
    client.post(f"/api/v1/orgs/{org['id']}/projects", json={"name": "P2"}, headers=auth_header)

    logs = client.get(
        f"/api/v1/orgs/{org['id']}/audit-logs",
        params={"action": "project.created"},
        headers=auth_header,
    ).json()["logs"]
    assert len(logs) == 2
    assert all(log["action"] == "project.created" for log in logs)
