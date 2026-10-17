"""Tests for the rate-limiting system -- algorithms are unit-tested directly
against the real dev Redis container (a Lua script's atomicity can't be
meaningfully faked), identity resolution and the middleware are integration
tests against the real dev Postgres + Redis containers together.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.cache.client import get_redis, init_redis
from backend.config import BackendConfig
from backend.ratelimit.algorithms import SlidingWindowLimiter, TokenBucketLimiter
from backend.ratelimit.identity import resolve_identity
from backend.ratelimit.plans import Plan, plan_limit


@pytest.fixture(autouse=True, scope="module")
def _ensure_redis():
    init_redis(BackendConfig.from_env().redis_url)


def _unique_key(prefix: str) -> str:
    return f"{prefix}:{uuid.uuid4().hex}"


@pytest.mark.unit
def test_plan_limit_known_plans():
    assert plan_limit(Plan.FREE.value).capacity == 60
    assert plan_limit(Plan.DEVELOPER.value).capacity == 600
    assert plan_limit(Plan.ENTERPRISE.value).capacity == 6000


@pytest.mark.unit
def test_plan_limit_unknown_string_falls_back_to_free():
    assert plan_limit("not-a-real-plan") == plan_limit(Plan.FREE.value)


@pytest.mark.integration
def test_sliding_window_allows_up_to_limit_then_denies():
    limiter = SlidingWindowLimiter(get_redis())
    key = _unique_key("test-sliding")
    now = 1_000_000.0

    results = [limiter.check(key, limit=3, window_seconds=60.0, now=now + i) for i in range(5)]

    assert [r.allowed for r in results] == [True, True, True, False, False]
    assert results[3].retry_after_seconds > 0


@pytest.mark.integration
def test_sliding_window_allows_again_after_window_passes():
    limiter = SlidingWindowLimiter(get_redis())
    key = _unique_key("test-sliding-expiry")

    for i in range(3):
        assert limiter.check(key, limit=3, window_seconds=10.0, now=1000.0 + i).allowed
    assert not limiter.check(key, limit=3, window_seconds=10.0, now=1003.0).allowed

    # 11 seconds later, the original 3 entries have aged out of a 10s window.
    assert limiter.check(key, limit=3, window_seconds=10.0, now=1014.0).allowed


@pytest.mark.integration
def test_token_bucket_allows_up_to_capacity_then_denies():
    limiter = TokenBucketLimiter(get_redis())
    key = _unique_key("test-bucket")
    now = 2_000_000.0

    # capacity=3, refill_rate effectively irrelevant within this instant.
    results = [
        limiter.check(key, capacity=3, refill_rate_per_second=0.001, now=now) for _ in range(5)
    ]

    assert [r.allowed for r in results] == [True, True, True, False, False]


@pytest.mark.integration
def test_token_bucket_refills_over_time():
    limiter = TokenBucketLimiter(get_redis())
    key = _unique_key("test-bucket-refill")

    for _ in range(2):
        assert limiter.check(key, capacity=2, refill_rate_per_second=1.0, now=3000.0).allowed
    assert not limiter.check(key, capacity=2, refill_rate_per_second=1.0, now=3000.0).allowed

    # 2 seconds later at 1 token/sec, a full token should be available again.
    assert limiter.check(key, capacity=2, refill_rate_per_second=1.0, now=3002.0).allowed


@pytest.mark.integration
def test_resolve_identity_anonymous_without_credentials():
    class _FakeClient:
        host = "127.0.0.1"

    class _FakeRequest:
        client = _FakeClient()
        headers: dict = {}

    identity = resolve_identity(_FakeRequest(), BackendConfig.from_env())
    assert identity.kind == "anonymous"
    assert identity.plan == Plan.FREE.value


@pytest.mark.integration
def test_resolve_identity_valid_bearer_token():
    client = TestClient(create_app())
    email = f"test-{uuid.uuid4().hex}@example.com"
    client.post("/api/v1/auth/register", json={"email": email, "password": "hunter2hunter"})
    tokens = client.post(
        "/api/v1/auth/login", json={"email": email, "password": "hunter2hunter"}
    ).json()

    class _FakeClient:
        host = "127.0.0.1"

    class _FakeRequest:
        client = _FakeClient()
        headers = {"authorization": f"Bearer {tokens['access_token']}"}

    identity = resolve_identity(_FakeRequest(), BackendConfig.from_env())
    assert identity.kind == "user"
    assert identity.identity_id is not None


@pytest.mark.integration
def test_resolve_identity_invalid_bearer_falls_back_to_anonymous():
    class _FakeClient:
        host = "127.0.0.1"

    class _FakeRequest:
        client = _FakeClient()
        headers = {"authorization": "Bearer not-a-real-token"}

    identity = resolve_identity(_FakeRequest(), BackendConfig.from_env())
    assert identity.kind == "anonymous"


@pytest.mark.integration
def test_resolve_identity_valid_api_key_does_not_raise():
    """Regression test: resolve_identity's API-key branch used to read
    key_row.revoked *after* its own session_scope() block had already
    exited, raising sqlalchemy.orm.exc.DetachedInstanceError for every
    single API-key-authenticated request (masked by the middleware's
    fail-open behavior, so it silently degraded to "treat as anonymous"
    instead of surfacing as a test failure until this test was added)."""
    client = TestClient(create_app())
    email = f"test-{uuid.uuid4().hex}@example.com"
    client.post("/api/v1/auth/register", json={"email": email, "password": "hunter2hunter"})
    tokens = client.post(
        "/api/v1/auth/login", json={"email": email, "password": "hunter2hunter"}
    ).json()
    auth_header = {"Authorization": f"Bearer {tokens['access_token']}"}
    key = client.post(
        "/api/v1/api-keys", json={"name": "ratelimit-test-key"}, headers=auth_header
    ).json()

    class _FakeClient:
        host = "127.0.0.1"

    class _FakeRequest:
        client = _FakeClient()
        headers = {"x-api-key": key["api_key"]}

    identity = resolve_identity(_FakeRequest(), BackendConfig.from_env())
    assert identity.kind == "api_key"
    assert identity.identity_id == key["id"]


@pytest.mark.integration
def test_middleware_enforces_identity_limit_for_authenticated_user():
    client = TestClient(create_app())
    email = f"test-{uuid.uuid4().hex}@example.com"
    client.post("/api/v1/auth/register", json={"email": email, "password": "hunter2hunter"})
    tokens = client.post(
        "/api/v1/auth/login", json={"email": email, "password": "hunter2hunter"}
    ).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    # Free plan capacity is 60 -- a fresh user/token-bucket key, so exactly
    # 60 requests succeed before the 61st is rejected.
    statuses = [client.get("/api/v1/auth/me", headers=headers).status_code for _ in range(61)]

    assert statuses.count(200) == 60
    assert statuses[-1] == 429


@pytest.mark.integration
def test_rate_limit_response_has_uniform_error_shape_and_retry_after():
    client = TestClient(create_app())
    email = f"test-{uuid.uuid4().hex}@example.com"
    client.post("/api/v1/auth/register", json={"email": email, "password": "hunter2hunter"})
    tokens = client.post(
        "/api/v1/auth/login", json={"email": email, "password": "hunter2hunter"}
    ).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    for _ in range(60):
        client.get("/api/v1/auth/me", headers=headers)
    response = client.get("/api/v1/auth/me", headers=headers)

    assert response.status_code == 429
    assert response.json()["error_type"] == "rate_limit_exceeded"
    assert "Retry-After" in response.headers


@pytest.mark.integration
def test_middleware_fails_open_when_redis_unreachable():
    """A broken rate limiter must not turn every request into a 500 --
    verified directly against the real middleware/app, not just the
    algorithm in isolation."""
    import backend.cache.client as client_module

    client_module._client = None
    init_redis("redis://localhost:1/0")
    try:
        client = TestClient(create_app(), raise_server_exceptions=False)
        response = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer whatever"})
        # 401 (invalid token, handled normally by the route) -- specifically
        # NOT 500 or 429, proving the rate limiter got out of the way rather
        # than crashing the request or blocking it.
        assert response.status_code == 401
    finally:
        client_module._client = None
        init_redis(BackendConfig.from_env().redis_url)
