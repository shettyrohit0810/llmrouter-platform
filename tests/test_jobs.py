import time

from backend.api.services.jobs import InMemoryJobStore, JobManager, JobStatus


def test_job_lifecycle_success():
    manager = JobManager(InMemoryJobStore())
    job = manager.submit("train", lambda: {"accuracy": 0.9})
    assert job.status == JobStatus.QUEUED

    manager.run(job.job_id, lambda: {"accuracy": 0.9})

    updated = manager.store.get(job.job_id)
    assert updated.status == JobStatus.COMPLETED
    assert updated.result == {"accuracy": 0.9}
    assert updated.started_at is not None
    assert updated.completed_at is not None


def test_job_lifecycle_failure_hides_traceback_from_result():
    manager = JobManager(InMemoryJobStore())
    job = manager.submit("benchmark", lambda: (_ for _ in ()).throw(ValueError("bad config")))

    def failing():
        raise ValueError("bad config")

    manager.run(job.job_id, failing)

    updated = manager.store.get(job.job_id)
    assert updated.status == JobStatus.FAILED
    assert updated.error == "bad config"
    assert "Traceback" not in (updated.error or "")


def test_job_store_list_orders_newest_first():
    store = InMemoryJobStore()
    j1 = store.create("train")
    time.sleep(0.01)
    j2 = store.create("benchmark")

    jobs = store.list()
    assert jobs[0].job_id == j2.job_id
    assert jobs[1].job_id == j1.job_id


def test_get_job_manager_returns_singleton():
    from backend.api.services.jobs import get_job_manager

    a = get_job_manager()
    b = get_job_manager()
    assert a is b
