"""Integration tests for the real worker queue (backend/worker/) -- require
the real dev Postgres container. They exercise the guarantees the queue
exists to provide: a job is never claimed twice concurrently, an abandoned
job is reclaimed once its lease expires, a job that keeps failing ends in
dead_letter instead of retrying forever, and re-running a job's work does
not duplicate its results.
"""

import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from backend.app import create_app
from backend.api.services.jobs import PostgresJobStore
from backend.db.models.experiments import Experiment
from backend.db.models.jobs import JobRecord, TrainingJobDetail
from backend.db.models.registry import RouterVersion
from backend.db.session import session_scope
from backend.worker.queue import claim_next_job, fail_or_requeue_job
from backend.worker.runner import _run_train


def _new_job(payload=None, job_type="train") -> uuid.UUID:
    job = PostgresJobStore().create(job_type, payload=payload or {"router": "x"})
    return uuid.UUID(job.job_id)


def _status(job_id: uuid.UUID) -> str:
    with session_scope() as db:
        return db.get(JobRecord, job_id).status


def _expire_lease(job_id: uuid.UUID) -> None:
    with session_scope() as db:
        db.execute(
            update(JobRecord)
            .where(JobRecord.id == job_id)
            .values(leased_until=datetime.now(timezone.utc) - timedelta(seconds=5))
        )


@pytest.mark.integration
def test_concurrent_workers_never_double_claim_a_job():
    """8 workers race for the same single job, 5 rounds: exactly one claim
    must ever win per round (FOR UPDATE SKIP LOCKED), never two."""
    for _ in range(5):
        job_id = _new_job()
        winners = []
        barrier = threading.Barrier(8)

        def attempt():
            barrier.wait()
            with session_scope() as db:
                claimed = claim_next_job(db, only_job_id=job_id)
            if claimed is not None:
                winners.append(claimed.job_id)

        threads = [threading.Thread(target=attempt) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert winners == [job_id]


@pytest.mark.integration
def test_expired_lease_is_reclaimed_and_counts_as_a_retry():
    job_id = _new_job()
    with session_scope() as db:
        first = claim_next_job(db, only_job_id=job_id)
    assert first is not None and first.retry_count == 0

    # A live lease means nobody else may take it.
    with session_scope() as db:
        assert claim_next_job(db, only_job_id=job_id) is None

    # The worker dies without finishing; its lease runs out.
    _expire_lease(job_id)
    with session_scope() as db:
        second = claim_next_job(db, only_job_id=job_id)
    assert second is not None
    assert second.retry_count == 1
    assert _status(job_id) == "running"


@pytest.mark.integration
def test_repeated_worker_crashes_end_in_dead_letter():
    job_id = _new_job()
    max_retries = 2
    for _ in range(max_retries + 1):
        with session_scope() as db:
            assert claim_next_job(db, only_job_id=job_id, max_retries=max_retries) is not None
        _expire_lease(job_id)

    # Budget spent: the next reclaim attempt dead-letters it instead.
    with session_scope() as db:
        assert claim_next_job(db, only_job_id=job_id, max_retries=max_retries) is None
    assert _status(job_id) == "dead_letter"


@pytest.mark.integration
def test_explicit_failures_requeue_then_dead_letter():
    job_id = _new_job()
    max_retries = 2
    statuses = []
    for _ in range(max_retries + 1):
        with session_scope() as db:
            assert claim_next_job(db, only_job_id=job_id, max_retries=max_retries) is not None
        with session_scope() as db:
            statuses.append(fail_or_requeue_job(db, job_id, "boom", max_retries=max_retries))

    assert statuses == ["queued", "queued", "dead_letter"]
    with session_scope() as db:
        assert claim_next_job(db, only_job_id=job_id) is None  # terminal


@pytest.mark.integration
def test_rerunning_a_train_job_does_not_duplicate_its_results():
    client = TestClient(create_app())
    email = f"test-{uuid.uuid4().hex}@example.com"
    client.post("/api/v1/auth/register", json={"email": email, "password": "hunter2hunter"})
    tokens = client.post(
        "/api/v1/auth/login", json={"email": email, "password": "hunter2hunter"}
    ).json()
    auth = {"Authorization": f"Bearer {tokens['access_token']}"}
    org = client.post(
        "/api/v1/orgs", json={"name": f"Org {uuid.uuid4().hex[:8]}"}, headers=auth
    ).json()
    project = client.post(
        f"/api/v1/orgs/{org['id']}/projects", json={"name": "Default"}, headers=auth
    ).json()

    payload = {
        "router": "elorouter",
        "config_path": "configs/train/elorouter.yaml",
        "device": "cpu",
        "create_experiment": True,
        "project_id": project["id"],
        "organization_id": org["id"],
        "api_key_id": None,
        "user_id": None,
    }
    job_id = _new_job(payload)

    # Simulates the double-execution a reclaim race could cause.
    _run_train(job_id, payload)
    _run_train(job_id, payload)

    with session_scope() as db:
        versions = db.query(RouterVersion).filter(RouterVersion.training_job_id == job_id).count()
        details = db.query(TrainingJobDetail).filter(TrainingJobDetail.job_id == job_id).count()
        experiments = db.query(Experiment).filter(Experiment.job_id == job_id).count()
    assert (versions, details, experiments) == (1, 1, 1)
