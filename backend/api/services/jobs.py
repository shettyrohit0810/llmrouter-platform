"""Generic background-job abstraction.

Every long-running backend operation (training, benchmarking, and future
work like embedding generation) goes through this same Job/JobStore/
JobManager stack rather than being implemented ad hoc per endpoint. The
JobStore is a Protocol specifically so Phase 4 can swap InMemoryJobStore for
a persistent one without any client-visible API change (see
docs/migration/phase2_to_phase3.md) -- Milestone 7 exercises that seam:
PostgresJobStore is now the default (see get_job_manager()), backed by
backend.db.models.jobs.JobRecord. InMemoryJobStore remains for fast unit
tests that don't need a real database.
"""

import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Protocol

from backend.observability.metrics import job_submissions_total

from backend.db.models.jobs import JobRecord
from backend.db.session import session_scope


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    # Terminal: retry budget exhausted (see backend/worker/queue.py). Distinct
    # from CANCELLED, which no code path sets -- reserved for a future
    # explicit user-cancel action, not "gave up retrying".
    DEAD_LETTER = "dead_letter"


@dataclass
class Job:
    job_id: str
    job_type: str  # "train" | "benchmark" | "benchmark_compare"
    status: JobStatus = JobStatus.QUEUED
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    progress: Optional[int] = None  # 0-100 when available
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    # Parameters an out-of-process worker needs to actually execute this job
    # (router name, config path, project-context ids, ...) -- see
    # backend/worker/. None for jobs submitted the old way (a bare fn,
    # executed in-process), which never populated this.
    payload: Optional[Dict[str, Any]] = None
    # Owning project (None for anonymous jobs). Read access to a project's
    # jobs is enforced in the API layer, see management.py.
    project_id: Optional[str] = None
    retry_count: int = 0
    leased_until: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "progress": self.progress,
            "result": self.result,
            "error": self.error,
        }


class JobStore(Protocol):
    """Interface every job-storage backend must satisfy (in-memory now, Redis-backed
    possible later without changing JobManager or any endpoint)."""

    def create(
        self,
        job_type: str,
        payload: Optional[Dict[str, Any]] = None,
        project_id: Optional[uuid.UUID] = None,
        created_by: Optional[uuid.UUID] = None,
    ) -> Job: ...
    def get(self, job_id: str) -> Optional[Job]: ...
    def update(self, job: Job) -> None: ...
    def list(self, limit: int = 50) -> List[Job]: ...
    def list_for_projects(self, project_ids: List[uuid.UUID], limit: int = 50) -> List[Job]: ...


class InMemoryJobStore:
    """Phase 3's only JobStore implementation. Process-local, not persisted --
    acceptable for a single-process backend with no infrastructure beyond
    itself, per this phase's explicit "no Redis/Celery/Postgres yet" scope."""

    def __init__(self) -> None:
        self._jobs: Dict[str, Job] = {}

    def create(
        self,
        job_type: str,
        payload: Optional[Dict[str, Any]] = None,
        project_id: Optional[uuid.UUID] = None,
        created_by: Optional[uuid.UUID] = None,
    ) -> Job:
        job = Job(
            job_id=str(uuid.uuid4()),
            job_type=job_type,
            payload=payload,
            project_id=str(project_id) if project_id else None,
        )
        self._jobs[job.job_id] = job
        return job

    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def update(self, job: Job) -> None:
        self._jobs[job.job_id] = job

    def list(self, limit: int = 50) -> List[Job]:
        return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)[:limit]

    def list_for_projects(self, project_ids: List[uuid.UUID], limit: int = 50) -> List[Job]:
        wanted = {str(p) for p in project_ids}
        return [j for j in self.list(limit=10_000) if j.project_id in wanted][:limit]


def _to_datetime(epoch: Optional[float]) -> Optional[datetime]:
    return datetime.fromtimestamp(epoch, tz=timezone.utc) if epoch is not None else None


def _to_epoch(dt: Optional[datetime]) -> Optional[float]:
    return dt.timestamp() if dt is not None else None


def _parse_job_id(job_id: str) -> Optional[uuid.UUID]:
    """A job_id that isn't a valid UUID can't possibly match a row -- treat
    it the same as "not found" (returning None) rather than letting
    uuid.UUID() raise ValueError and turn a client's bad ID into a 500.
    (This was a real gap: GET /api/v1/jobs/does-not-exist worked fine
    against InMemoryJobStore's plain dict lookup, since any string is a
    valid dict key, but crashed against PostgresJobStore before this
    guard was added.)"""
    try:
        return uuid.UUID(job_id)
    except ValueError:
        return None


def _job_from_record(record: Any) -> Job:
    return Job(
        job_id=str(record.id),
        job_type=record.job_type,
        status=JobStatus(record.status),
        created_at=_to_epoch(record.created_at) or time.time(),
        started_at=_to_epoch(record.started_at),
        completed_at=_to_epoch(record.completed_at),
        progress=record.progress,
        result=record.result,
        error=record.error,
        payload=record.payload,
        project_id=str(record.project_id) if record.project_id else None,
        retry_count=record.retry_count,
        leased_until=_to_epoch(record.leased_until),
    )


class PostgresJobStore:
    """Persists jobs in the `jobs` table (backend.db.models.jobs.JobRecord)
    instead of an in-memory dict -- a job's status/result/error survives a
    process restart, and any process can see any job (not just the one that
    submitted it).

    Opens its own session per method call via session_scope() rather than
    taking a Session parameter, because JobStore's Protocol doesn't thread
    one through -- JobManager.run() executes via FastAPI BackgroundTasks,
    after the request that submitted the job (and its DI-provided session)
    has already completed.

    `project_id`/`created_by`/`logs` exist on JobRecord but aren't populated
    here -- this class only ever backed the old in-process BackgroundTasks
    execution path (JobManager.run()), which never had an authenticated
    project context or a retry policy to record. `retry_count`/`leased_until`
    are now populated too, but only by backend/worker/queue.py's claim/lease
    logic (raw SQL, not this class's update()) -- the real worker queue
    needs atomic claim semantics (SELECT ... FOR UPDATE SKIP LOCKED) this
    class's plain get()-then-update() can't provide."""

    def create(
        self,
        job_type: str,
        payload: Optional[Dict[str, Any]] = None,
        project_id: Optional[uuid.UUID] = None,
        created_by: Optional[uuid.UUID] = None,
    ) -> Job:
        with session_scope() as db:
            record = JobRecord(
                job_type=job_type,
                status=JobStatus.QUEUED.value,
                payload=payload,
                project_id=project_id,
                created_by=created_by,
            )
            db.add(record)
            db.flush()
            db.refresh(record)
            return _job_from_record(record)

    def get(self, job_id: str) -> Optional[Job]:
        parsed = _parse_job_id(job_id)
        if parsed is None:
            return None
        with session_scope() as db:
            record = db.get(JobRecord, parsed)
            return _job_from_record(record) if record is not None else None

    def update(self, job: Job) -> None:
        parsed = _parse_job_id(job.job_id)
        if parsed is None:
            return
        with session_scope() as db:
            record = db.get(JobRecord, parsed)
            if record is None:
                return
            record.status = job.status.value
            record.progress = job.progress
            record.result = job.result
            record.error = job.error
            record.started_at = _to_datetime(job.started_at)
            record.completed_at = _to_datetime(job.completed_at)

    def list(self, limit: int = 50) -> List[Job]:
        with session_scope() as db:
            records = db.query(JobRecord).order_by(JobRecord.created_at.desc()).limit(limit).all()
            return [_job_from_record(r) for r in records]

    def list_for_projects(self, project_ids: List[uuid.UUID], limit: int = 50) -> List[Job]:
        if not project_ids:
            return []
        with session_scope() as db:
            records = (
                db.query(JobRecord)
                .filter(JobRecord.project_id.in_(project_ids))
                .order_by(JobRecord.created_at.desc())
                .limit(limit)
                .all()
            )
            return [_job_from_record(r) for r in records]


class JobManager:
    """Submits work through the JobStore rather than executing it directly --
    FastAPI route handlers call JobManager.submit(), never the JobStore or the
    underlying llmrouter function directly, so the execution mechanism
    (BackgroundTasks now, a real worker queue later) can change without
    touching endpoint code."""

    def __init__(self, store: JobStore):
        self.store = store

    def submit(
        self,
        job_type: str,
        fn: Optional[Callable[[], Dict[str, Any]]] = None,
        *,
        payload: Optional[Dict[str, Any]] = None,
        project_id: Optional[uuid.UUID] = None,
        created_by: Optional[uuid.UUID] = None,
    ) -> Job:
        """Create a job and return it immediately (still QUEUED).

        Two mutually-exclusive execution paths, both going through this
        same submit() so callers never construct a Job directly:
        - `fn` (legacy): call `run(job.job_id, fn)` from a BackgroundTasks
          callback to execute it in-process, after this request returns.
        - `payload` (backend/worker/): an out-of-process worker polls the
          `jobs` table, claims this row, and reconstructs what to do from
          `payload` -- no in-memory closure involved, since the worker runs
          in a different process than the one that called submit().
        """
        job_submissions_total.labels(job_type=job_type).inc()
        return self.store.create(
            job_type, payload=payload, project_id=project_id, created_by=created_by
        )

    def run(self, job_id: str, fn: Callable[[], Dict[str, Any]]) -> None:
        """Execute `fn`, updating the job's status/result/error/timestamps.
        Intended to be handed to FastAPI's BackgroundTasks, not called inline
        during request handling."""
        job = self.store.get(job_id)
        if job is None:
            return
        job.status = JobStatus.RUNNING
        job.started_at = time.time()
        self.store.update(job)
        try:
            result = fn()
            job.status = JobStatus.COMPLETED
            job.result = result
        except Exception as exc:
            job.status = JobStatus.FAILED
            # Never expose a raw traceback to API clients (Milestone 6's rule) --
            # store it here for server-side logs/debugging only, expose just the message.
            job.error = str(exc)
            self._log_traceback(job_id, exc)
        finally:
            job.completed_at = time.time()
            self.store.update(job)

    @staticmethod
    def _log_traceback(job_id: str, exc: Exception) -> None:
        import logging

        logging.getLogger("backend.jobs").error(
            "Job %s failed: %s\n%s", job_id, exc, traceback.format_exc()
        )


# Module-level singleton -- one JobManager per process. Phase 3 wired this to
# InMemoryJobStore; Milestone 7 switches the default to PostgresJobStore so
# jobs survive a restart -- no other line in this module or in
# backend/api/routers/management.py changes, since both implement the same
# JobStore Protocol.
_job_manager: Optional[JobManager] = None


def get_job_manager() -> JobManager:
    global _job_manager
    if _job_manager is None:
        _job_manager = JobManager(PostgresJobStore())
    return _job_manager
