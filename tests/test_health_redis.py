"""Integration tests for the Redis-backed portion of /health -- mirrors
tests/backend/test_health_db.py's pattern for the database check."""

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.cache.client import check_connection, init_redis


@pytest.mark.unit
def test_check_connection_false_for_unreachable_redis():
    # init_redis() is idempotent (no-op if a client already exists from an
    # earlier test's create_app() call), so the module-level singleton must
    # be cleared first -- same caveat as backend/db/session.py's equivalent.
    import backend.cache.client as client_module

    client_module._client = None
    init_redis("redis://localhost:1/0")
    assert check_connection() is False
    client_module._client = None


def test_health_returns_503_when_redis_unreachable():
    import backend.cache.client as client_module

    client_module._client = None
    init_redis("redis://localhost:1/0")
    try:
        client = TestClient(create_app(), raise_server_exceptions=False)
        response = client.get("/health")
        assert response.status_code == 503
    finally:
        client_module._client = None
