"""Integration tests for PostgresJobStore -- require the local dev Postgres
container. Mirrors tests/backend/test_jobs.py's InMemoryJobStore test shapes
where applicable, plus a dedicated test proving jobs survive process
restarts (the actual point of Milestone 7), not just that the class methods
work in isolation.
"""

import time

import pytest

from backend.api.services.jobs import (
    InMemoryJobStore,
    JobManager,
    JobStatus,
    PostgresJobStore,
    get_job_manager,
)
from backend.config import BackendConfig
from backend.db.session import init_engine


@pytest.fixture(autouse=True, scope="module")
def _ensure_engine():
    # Lets this file run standalone without depending on another test
    # module having already called create_app() -> init_engine() first.
    init_engine(BackendConfig.from_env().database_url)


@pytest.mark.integration
def test_postgres_job_store_lifecycle():
    manager = JobManager(PostgresJobStore())
    job = manager.submit("train", lambda: {"accuracy": 0.9})
    assert job.status == JobStatus.QUEUED

    manager.run(job.job_id, lambda: {"accuracy": 0.9})

    updated = manager.store.get(job.job_id)
    assert updated.status == JobStatus.COMPLETED
    assert updated.result == {"accuracy": 0.9}
    assert updated.started_at is not None
    assert updated.completed_at is not None


@pytest.mark.integration
def test_postgres_job_store_failure_hides_traceback():
    manager = JobManager(PostgresJobStore())
    job = manager.submit("benchmark", lambda: None)

    def failing():
        raise ValueError("bad config")

    manager.run(job.job_id, failing)

    updated = manager.store.get(job.job_id)
    assert updated.status == JobStatus.FAILED
    assert updated.error == "bad config"
    assert "Traceback" not in (updated.error or "")


@pytest.mark.integration
def test_postgres_job_store_list_orders_newest_first():
    store = PostgresJobStore()
    j1 = store.create("train")
    time.sleep(0.05)
    j2 = store.create("benchmark")

    jobs = store.list(limit=2)
    assert jobs[0].job_id == j2.job_id
    assert jobs[1].job_id == j1.job_id


@pytest.mark.integration
def test_postgres_job_store_get_missing_returns_none():
    store = PostgresJobStore()
    assert store.get("00000000-0000-0000-0000-000000000000") is None


@pytest.mark.integration
def test_postgres_job_store_get_malformed_id_returns_none_not_raises():
    """Regression test: a job_id that isn't a valid UUID (e.g. a client
    hitting GET /api/v1/jobs/does-not-exist) must be treated as "not found",
    not crash with uuid.UUID()'s ValueError -- this was a real 500 caught
    while adding Milestone 7's persistent store."""
    store = PostgresJobStore()
    assert store.get("does-not-exist") is None


@pytest.mark.integration
def test_job_survives_across_independent_store_instances():
    """The actual point of Milestone 7: a job created through one
    PostgresJobStore instance (simulating one request/process) must be
    readable through a completely separate instance (simulating a
    subsequent request after a restart) -- proving state lives in Postgres,
    not in any Python-level object."""
    writer = PostgresJobStore()
    job = writer.create("train")
    del writer  # the point: nothing about `job`'s data lives on this object

    reader = PostgresJobStore()
    fetched = reader.get(job.job_id)
    assert fetched is not None
    assert fetched.job_type == "train"
    assert fetched.status == JobStatus.QUEUED


@pytest.mark.integration
def test_in_memory_store_does_not_see_postgres_jobs():
    """Confirms the two implementations are genuinely independent -- a job
    created via Postgres is invisible to a fresh InMemoryJobStore, ruling
    out any accidental shared state between the two."""
    pg_store = PostgresJobStore()
    job = pg_store.create("train")

    memory_store = InMemoryJobStore()
    assert memory_store.get(job.job_id) is None


@pytest.mark.integration
def test_get_job_manager_uses_postgres_job_store_by_default():
    manager = get_job_manager()
    assert isinstance(manager.store, PostgresJobStore)
