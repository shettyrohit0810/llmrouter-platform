"""Integration tests for the DB-backed /health check.

test_health_ok_when_database_reachable requires the local dev Postgres
container (docker/docker-compose.yml's `postgres` service, or
`docker run ... postgres:16-alpine` per docs/backend/database.md) to be
running and reachable at BackendConfig.database_url -- consistent with this
project's existing convention of integration tests exercising a real
dependency rather than a mock (see tests/ pytest markers)."""

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.db.session import check_connection, init_engine


@pytest.mark.integration
def test_health_ok_when_database_reachable():
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.unit
def test_check_connection_false_for_unreachable_database():
    # A syntactically valid but unroutable DSN -- no real network dependency,
    # just proves check_connection() catches the failure instead of raising.
    # init_engine() is idempotent (no-op if an engine already exists from an
    # earlier test's create_app() call), so the module-level singleton must be
    # cleared first or this would silently check the real, working engine.
    import backend.db.session as session_module

    session_module._engine = None
    session_module._SessionLocal = None
    init_engine("postgresql+psycopg2://user:pass@localhost:1/nonexistent")
    assert check_connection() is False
    session_module._engine = None
    session_module._SessionLocal = None


def test_health_returns_503_when_database_unreachable():
    import backend.db.session as session_module

    session_module._engine = None
    session_module._SessionLocal = None
    init_engine("postgresql+psycopg2://user:pass@localhost:1/nonexistent")
    try:
        client = TestClient(create_app(), raise_server_exceptions=False)
        response = client.get("/health")
        assert response.status_code == 503
    finally:
        session_module._engine = None
        session_module._SessionLocal = None
