"""Tests for the Redis caching layer.

test_check_connection_* and the four *_cache tests are integration tests
requiring the local dev Redis container (see docs/backend/caching.md).
test_stable_key_* are unit tests, no external dependency.
"""

import uuid

import pytest

from backend.cache.caches import embedding_cache, job_cache, prediction_cache, session_cache
from backend.cache.client import check_connection, get_redis, init_redis
from backend.cache.keys import stable_key
from backend.config import BackendConfig


@pytest.fixture(autouse=True, scope="module")
def _ensure_redis():
    init_redis(BackendConfig.from_env().redis_url)


def _unique_key() -> str:
    return uuid.uuid4().hex


@pytest.mark.unit
def test_stable_key_is_deterministic():
    assert stable_key("a", "b") == stable_key("a", "b")


@pytest.mark.unit
def test_stable_key_avoids_naive_concatenation_collision():
    assert stable_key("a", "bc") != stable_key("ab", "c")


@pytest.mark.integration
def test_check_connection_true_when_redis_reachable():
    assert check_connection() is True


@pytest.mark.integration
def test_generic_cache_get_set_delete_roundtrip():
    key = _unique_key()
    assert job_cache.get(key) is None

    job_cache.set(key, {"status": "running"})
    assert job_cache.get(key) == {"status": "running"}

    job_cache.delete(key)
    assert job_cache.get(key) is None


@pytest.mark.integration
def test_cache_namespaces_do_not_collide():
    key = _unique_key()
    session_cache.set(key, {"who": "session"})
    job_cache.set(key, {"who": "job"})

    assert session_cache.get(key) == {"who": "session"}
    assert job_cache.get(key) == {"who": "job"}


@pytest.mark.integration
def test_get_or_set_only_computes_on_miss():
    key = _unique_key()
    calls = []

    def compute():
        calls.append(1)
        return {"computed": True}

    first = embedding_cache.get_or_set(key, compute)
    second = embedding_cache.get_or_set(key, compute)

    assert first == {"computed": True}
    assert second == {"computed": True}
    assert len(calls) == 1


@pytest.mark.integration
def test_ttl_expiry_is_applied():
    key = _unique_key()
    prediction_cache.set(key, {"router": "knnrouter"}, ttl_seconds=1)
    assert get_redis().ttl(f"prediction:{key}") in (0, 1)
