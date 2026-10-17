"""Shared fixtures for tests/backend/.

Rate-limit state (Milestone 6) lives in the same real, persistent Redis
container every test in this directory shares -- and every TestClient
request looks like it comes from the same IP ("testclient"). Without reset,
one test's requests count toward another, unrelated test's quota, causing
spurious 429s anywhere in the suite that happens to run after a
request-heavy test. A real deployment never sees this (traffic from one
client is spread over real time, not compressed into milliseconds the way a
test run is) -- this is purely a test-isolation concern, not a production
rate-limiting change.
"""

import pytest


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    from backend.cache.client import get_redis, init_redis
    from backend.config import BackendConfig

    try:
        client = get_redis()
    except RuntimeError:
        client = init_redis(BackendConfig.from_env().redis_url)

    for key in client.scan_iter("ratelimit:*"):
        client.delete(key)

    yield
