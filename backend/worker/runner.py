"""Executes a claimed job's actual work -- train/benchmark/benchmark_compare
-- reconstructing what to do entirely from `payload` (no in-memory closure;
this runs in a separate process from the one that received the HTTP
request, via backend/worker/main.py's poll loop, not FastAPI BackgroundTasks).

Same auxiliary bookkeeping (RouterVersion/TrainingJobDetail/Experiment/
UsageRecord) management.py's old BackgroundTasks closures used to do, kept
line-for-line equivalent, but idempotent throughout -- registry.py's
register_router_version() and experiments.py's create_experiment() both
check-then-create keyed on job_id, and TrainingJobDetail (unique on job_id
at the DB level) gets the same check here -- since a reclaim after a crash,
or a retry after a transient failure, can call this more than once for the
same job_id.
"""

import logging
import threading
import time
import uuid
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from backend.api.services import experiments, registry, usage
from backend.api.services.config_resolver import read_save_model_path, resolve_config
from backend.db.models.jobs import TrainingJobDetail
from backend.db.session import session_scope
from backend.worker.config import HEARTBEAT_INTERVAL_SECONDS
from backend.worker.queue import ClaimedJob, complete_job, fail_or_requeue_job, renew_lease

logger = logging.getLogger("backend.worker.runner")


class _Heartbeat:
    """Runs renew_lease() on a background thread every
    HEARTBEAT_INTERVAL_SECONDS while the work function (a long, blocking
    call) executes on the main thread -- so another worker doesn't
    mistake this job for abandoned mid-run."""

    def __init__(self, job_id: UUID):
        self._job_id = job_id
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.wait(HEARTBEAT_INTERVAL_SECONDS):
            try:
                renew_lease(self._job_id)
            except Exception:
                logger.exception("Heartbeat renewal failed for job %s", self._job_id)

    def __enter__(self) -> "_Heartbeat":
        self._thread.start()
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self._stop.set()
        self._thread.join(timeout=5)


def _ids(payload: Dict[str, Any]) -> Dict[str, Optional[UUID]]:
    def _uuid_or_none(key: str) -> Optional[UUID]:
        value = payload.get(key)
        return UUID(value) if value else None

    return {
        "project_id": _uuid_or_none("project_id"),
        "organization_id": _uuid_or_none("organization_id"),
        "api_key_id": _uuid_or_none("api_key_id"),
        "user_id": _uuid_or_none("user_id"),
    }


def _record_usage_safe(db: Session, ids: Dict[str, Optional[UUID]], **kwargs: Any) -> None:
    if ids["project_id"] is None or ids["organization_id"] is None:
        return
    try:
        usage.record_usage(
            db,
            organization_id=ids["organization_id"],
            project_id=ids["project_id"],
            api_key_id=ids["api_key_id"],
            user_id=ids["user_id"],
            status_code=200,
            **kwargs,
        )
    except Exception:
        db.rollback()
        logger.exception("Failed to record usage")


def _run_train(job_id: UUID, payload: Dict[str, Any]) -> Dict[str, Any]:
    from llmrouter.cli.router_train import train_router

    router_name = payload["router"]
    config_path = payload["config_path"]
    device = payload.get("device", "cpu")
    ids = _ids(payload)

    start = time.time()
    train_router(
        router_name=router_name,
        config_path=resolve_config(config_path),
        device=device,
        verbose=False,
    )
    duration = time.time() - start

    # Both blocks below are auxiliary bookkeeping -- a failure in either
    # must never turn a successful training run into a failed job. Each
    # gets its own try/except, same as the original management.py handler.
    router_version_id = None
    checkpoint_path = read_save_model_path(config_path)
    if checkpoint_path is not None:
        try:
            with session_scope() as db:
                version = registry.register_router_version(
                    db,
                    router_name=router_name,
                    version_label=f"train-{uuid.uuid4().hex[:8]}",
                    checkpoint_path=checkpoint_path,
                    training_job_id=job_id,
                    project_id=ids["project_id"],
                    metadata={"config_path": config_path, "device": device},
                )
                router_version_id = version.id
                existing_detail = (
                    db.query(TrainingJobDetail).filter(TrainingJobDetail.job_id == job_id).first()
                )
                if existing_detail is None:
                    db.add(
                        TrainingJobDetail(
                            job_id=job_id,
                            router_name=router_name,
                            config_path=config_path,
                            device=device,
                            router_version_id=router_version_id,
                        )
                    )
        except Exception:
            logger.exception(
                "Failed to register router version/training job detail for job %s", job_id
            )

    if payload.get("create_experiment") and ids["project_id"] is not None:
        try:
            with session_scope() as db:
                experiments.create_experiment(
                    db,
                    project_id=ids["project_id"],
                    job_id=job_id,
                    experiment_type="train",
                    router_name=router_name,
                    router_version=str(router_version_id) if router_version_id else None,
                    metadata={"device": device, "config_path": config_path},
                    duration_seconds=duration,
                    created_by=ids["user_id"],
                )
        except Exception:
            logger.exception("Failed to create experiment record for train job %s", job_id)

    with session_scope() as db:
        _record_usage_safe(
            db, ids, endpoint="/api/v1/train", router_name=router_name, latency_ms=duration * 1000
        )

    return {"router": router_name, "config_path": config_path}


def _run_benchmark(job_id: UUID, payload: Dict[str, Any]) -> Dict[str, Any]:
    from backend.api.services.benchmark import run_benchmark

    router_name = payload["router"]
    config_path = payload["config_path"]
    dataset = payload.get("dataset", "default")
    sample_size = payload.get("sample_size")
    ids = _ids(payload)

    start = time.time()
    result = run_benchmark(router_name, config_path, dataset, sample_size)
    duration = time.time() - start

    if payload.get("create_experiment") and ids["project_id"] is not None:
        try:
            with session_scope() as db:
                experiments.create_experiment(
                    db,
                    project_id=ids["project_id"],
                    job_id=job_id,
                    experiment_type="benchmark",
                    router_name=router_name,
                    metrics={
                        "accuracy": result.accuracy,
                        "average_latency_seconds": result.average_latency_seconds,
                        "average_token_usage": result.average_token_usage,
                        "failures": result.failures,
                    },
                    metadata={"dataset": dataset, "sample_size": sample_size},
                    duration_seconds=duration,
                    created_by=ids["user_id"],
                )
        except Exception:
            logger.exception("Failed to create experiment record for benchmark job %s", job_id)

    with session_scope() as db:
        _record_usage_safe(
            db,
            ids,
            endpoint="/api/v1/benchmark",
            router_name=router_name,
            latency_ms=duration * 1000,
            # average_token_usage is a plain float (never None) -- 0 here is
            # a real value (no queries scored), not "unknown".
            tokens_output=round(result.average_token_usage),
        )

    return result.model_dump()


def _run_benchmark_compare(job_id: UUID, payload: Dict[str, Any]) -> Dict[str, Any]:
    from backend.api.schemas.benchmark import BenchmarkCompareResult
    from backend.api.services.benchmark import run_benchmark_compare

    config_paths = payload["config_paths"]
    routers = payload.get("routers", list(config_paths.keys()))
    dataset = payload.get("dataset", "default")
    sample_size = payload.get("sample_size")
    ids = _ids(payload)

    start = time.time()
    results = run_benchmark_compare(config_paths, dataset, sample_size)
    ranking = [r.router for r in results]
    duration = time.time() - start

    if payload.get("create_experiment") and ids["project_id"] is not None:
        try:
            with session_scope() as db:
                experiments.create_experiment(
                    db,
                    project_id=ids["project_id"],
                    job_id=job_id,
                    experiment_type="benchmark_compare",
                    metrics={"ranking": ranking},
                    metadata={"routers": routers, "dataset": dataset},
                    duration_seconds=duration,
                    created_by=ids["user_id"],
                )
        except Exception:
            logger.exception(
                "Failed to create experiment record for benchmark_compare job %s", job_id
            )

    with session_scope() as db:
        _record_usage_safe(
            db, ids, endpoint="/api/v1/benchmark/compare", latency_ms=duration * 1000
        )

    return BenchmarkCompareResult(leaderboard=results, ranking=ranking).model_dump()


_DISPATCH = {
    "train": _run_train,
    "benchmark": _run_benchmark,
    "benchmark_compare": _run_benchmark_compare,
}


def run_claimed_job(claimed: ClaimedJob) -> None:
    """Runs a claimed job's actual work, with a heartbeat thread renewing
    its lease throughout, and records the outcome: COMPLETED, or
    QUEUED-for-retry/DEAD_LETTER (via fail_or_requeue_job's own retry-budget
    check) on failure."""
    work_fn = _DISPATCH.get(claimed.job_type)
    if work_fn is None:
        logger.error(
            "Unknown job_type %r for job %s -- no dispatcher registered",
            claimed.job_type,
            claimed.job_id,
        )
        with session_scope() as db:
            fail_or_requeue_job(db, claimed.job_id, f"Unknown job_type '{claimed.job_type}'")
        return

    with _Heartbeat(claimed.job_id):
        try:
            result = work_fn(claimed.job_id, claimed.payload)
        except Exception as exc:
            logger.exception("Job %s failed", claimed.job_id)
            with session_scope() as db:
                status = fail_or_requeue_job(db, claimed.job_id, str(exc))
            logger.info(
                "Job %s -> %s (attempt %d)", claimed.job_id, status, claimed.retry_count + 1
            )
            return

    with session_scope() as db:
        complete_job(db, claimed.job_id, result)
