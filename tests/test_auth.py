"""Integration tests for the auth API -- require the local dev Postgres
container (see docs/backend/database.md), same convention as
tests/backend/test_health_db.py. Each test uses a unique, uuid-based email so
tests are independent and safely rerunnable against the same database."""

import uuid

import pytest
from fastapi.testclient import TestClient

from backend.api.auth import service
from backend.app import create_app
from backend.config import BackendConfig


def _unique_email() -> str:
    return f"test-{uuid.uuid4().hex}@example.com"


class _CapturingEmailSender:
    """Test double for EmailSender that captures the token instead of
    logging it, so tests don't have to parse ConsoleEmailSender's log line."""

    def __init__(self):
        self.last_body: str | None = None

    def send(self, *, to: str, subject: str, body: str) -> None:
        self.last_body = body


@pytest.fixture()
def client():
    return TestClient(create_app())


@pytest.mark.integration
def test_register_then_login(client):
    email = _unique_email()
    r = client.post("/api/v1/auth/register", json={"email": email, "password": "hunter2hunter"})
    assert r.status_code == 201
    assert r.json()["email"] == email
    assert r.json()["is_email_verified"] is False

    r = client.post("/api/v1/auth/login", json={"email": email, "password": "hunter2hunter"})
    assert r.status_code == 200
    body = r.json()
    assert "access_token" in body and "refresh_token" in body


@pytest.mark.integration
def test_duplicate_registration_conflicts(client):
    email = _unique_email()
    client.post("/api/v1/auth/register", json={"email": email, "password": "hunter2hunter"})
    r = client.post("/api/v1/auth/register", json={"email": email, "password": "hunter2hunter"})
    assert r.status_code == 409


@pytest.mark.integration
def test_login_wrong_password_rejected(client):
    email = _unique_email()
    client.post("/api/v1/auth/register", json={"email": email, "password": "hunter2hunter"})
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "wrong"})
    assert r.status_code == 401


@pytest.mark.integration
def test_login_unknown_email_rejected(client):
    r = client.post("/api/v1/auth/login", json={"email": _unique_email(), "password": "irrelevant"})
    assert r.status_code == 401


@pytest.mark.integration
def test_me_requires_valid_bearer_token(client):
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 422  # missing required Authorization header

    r = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401


@pytest.mark.integration
def test_me_returns_current_user(client):
    email = _unique_email()
    client.post("/api/v1/auth/register", json={"email": email, "password": "hunter2hunter"})
    tokens = client.post(
        "/api/v1/auth/login", json={"email": email, "password": "hunter2hunter"}
    ).json()

    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert r.status_code == 200
    assert r.json()["email"] == email


@pytest.mark.integration
def test_refresh_rotates_and_revokes_old_token(client):
    email = _unique_email()
    client.post("/api/v1/auth/register", json={"email": email, "password": "hunter2hunter"})
    tokens = client.post(
        "/api/v1/auth/login", json={"email": email, "password": "hunter2hunter"}
    ).json()

    r = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 200
    new_tokens = r.json()
    assert new_tokens["refresh_token"] != tokens["refresh_token"]

    # Old refresh token was revoked by rotation -- reusing it must fail.
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 401


@pytest.mark.integration
def test_logout_revokes_refresh_token(client):
    email = _unique_email()
    client.post("/api/v1/auth/register", json={"email": email, "password": "hunter2hunter"})
    tokens = client.post(
        "/api/v1/auth/login", json={"email": email, "password": "hunter2hunter"}
    ).json()

    r = client.post("/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 204

    r = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 401


@pytest.mark.integration
def test_password_reset_request_always_returns_202(client):
    # Registered or not -- no user-enumeration signal via status code.
    r = client.post("/api/v1/auth/password-reset/request", json={"email": _unique_email()})
    assert r.status_code == 202


@pytest.mark.integration
def test_password_reset_confirm_changes_password_and_is_single_use(client):
    email = _unique_email()
    client.post("/api/v1/auth/register", json={"email": email, "password": "old-password-1"})

    config = BackendConfig.from_env()
    from backend.db.session import session_scope

    sender = _CapturingEmailSender()
    with session_scope() as db:
        service.request_password_reset(db, config, sender, email=email)
    reset_token = sender.last_body.rsplit(": ", 1)[-1]

    r = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": reset_token, "new_password": "new-password-2"},
    )
    assert r.status_code == 204

    # Old password no longer works, new one does.
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "old-password-1"})
    assert r.status_code == 401
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "new-password-2"})
    assert r.status_code == 200

    # Reusing the same reset token must fail (fingerprint no longer matches).
    r = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": reset_token, "new_password": "another-3"},
    )
    assert r.status_code == 400


@pytest.mark.integration
def test_password_reset_confirm_rejects_garbage_token(client):
    r = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": "not-a-real-token", "new_password": "whatever-123"},
    )
    assert r.status_code == 400


@pytest.mark.integration
def test_email_verification_confirm_rejects_garbage_token(client):
    r = client.post("/api/v1/auth/email/verify", json={"token": "not-a-real-token"})
    assert r.status_code == 400


@pytest.mark.integration
def test_api_key_create_list_revoke_lifecycle(client):
    email = _unique_email()
    client.post("/api/v1/auth/register", json={"email": email, "password": "hunter2hunter"})
    tokens = client.post(
        "/api/v1/auth/login", json={"email": email, "password": "hunter2hunter"}
    ).json()
    auth_header = {"Authorization": f"Bearer {tokens['access_token']}"}

    r = client.post("/api/v1/api-keys", json={"name": "ci"}, headers=auth_header)
    assert r.status_code == 201
    created = r.json()
    assert created["api_key"].startswith("lr_live_")
    assert created["key_prefix"] == created["api_key"][:12]

    r = client.get("/api/v1/api-keys", headers=auth_header)
    assert r.status_code == 200
    assert len(r.json()["api_keys"]) == 1
    assert "api_key" not in r.json()["api_keys"][0]  # full key never re-listed

    r = client.delete(f"/api/v1/api-keys/{created['id']}", headers=auth_header)
    assert r.status_code == 204

    # Revoke is idempotent -- revoking an already-revoked key is a no-op, not
    # an error (standard DELETE semantics).
    r = client.delete(f"/api/v1/api-keys/{created['id']}", headers=auth_header)
    assert r.status_code == 204

    # A genuinely nonexistent key ID is the actual 404 case.
    r = client.delete(f"/api/v1/api-keys/{uuid.uuid4()}", headers=auth_header)
    assert r.status_code == 404


@pytest.mark.integration
def test_api_key_revoke_rejects_other_users_key(client):
    email_a, email_b = _unique_email(), _unique_email()
    client.post("/api/v1/auth/register", json={"email": email_a, "password": "hunter2hunter"})
    client.post("/api/v1/auth/register", json={"email": email_b, "password": "hunter2hunter"})
    token_a = client.post(
        "/api/v1/auth/login", json={"email": email_a, "password": "hunter2hunter"}
    ).json()["access_token"]
    token_b = client.post(
        "/api/v1/auth/login", json={"email": email_b, "password": "hunter2hunter"}
    ).json()["access_token"]

    key = client.post(
        "/api/v1/api-keys",
        json={"name": "a-key"},
        headers={"Authorization": f"Bearer {token_a}"},
    ).json()

    r = client.delete(
        f"/api/v1/api-keys/{key['id']}", headers={"Authorization": f"Bearer {token_b}"}
    )
    assert r.status_code == 404


@pytest.mark.integration
def test_oauth_login_returns_501_when_not_configured(client):
    r = client.get("/api/v1/auth/oauth/google/login")
    assert r.status_code == 501

    r = client.get("/api/v1/auth/oauth/github/login")
    assert r.status_code == 501


@pytest.mark.integration
def test_oauth_login_unknown_provider_returns_404(client):
    r = client.get("/api/v1/auth/oauth/not-a-real-provider/login")
    assert r.status_code == 404
