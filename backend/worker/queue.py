"""Queue primitives: atomic claim, lease renewal, and terminal-state
transitions -- all directly against backend.db.models.jobs.JobRecord, not
through JobStore's Protocol (get()/update() only offer a plain read-then-
write, not the atomic claim semantics a real queue needs).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.db.models.jobs import JobRecord
from backend.db.session import session_scope
from backend.worker.config import LEASE_SECONDS, MAX_RETRIES


@dataclass
class ClaimedJob:
    """Plain-value snapshot of a claimed row -- not the live ORM object.
    claim_next_job() commits (and thus expires) the record it claims before
    returning; extracting primitives here, inside the same transaction,
    avoids a DetachedInstanceError the moment the caller's session closes
    and the job's actual execution (which can run far longer than the claim
    itself) begins."""

    job_id: UUID
    job_type: str
    payload: Dict[str, Any]
    retry_count: int


def claim_next_job(
    db: Session,
    *,
    lease_seconds: float = LEASE_SECONDS,
    max_retries: int = MAX_RETRIES,
    only_job_id: Optional[UUID] = None,
) -> Optional[ClaimedJob]:
    """Atomically claims the oldest eligible job: QUEUED, or RUNNING with an
    expired lease (its previous worker died without finishing). Returns
    None if there's nothing to claim, or if the only eligible row just got
    dead-lettered for exceeding its retry budget (the caller should just
    poll again).

    `db` should be a short-lived session scoped to this claim call alone --
    this function commits internally, and the caller is expected to use a
    separate session for the job's actual (possibly long) execution rather
    than holding one connection for the whole duration.
    """
    now = datetime.now(timezone.utc)
    stmt = select(JobRecord).where(
        (JobRecord.status == "queued")
        | ((JobRecord.status == "running") & (JobRecord.leased_until < now))
    )
    if only_job_id is not None:
        # Claim one specific job (still honoring lease/status rules) rather
        # than the oldest eligible one -- used by tests, and by anything
        # that needs "run this job now" semantics.
        stmt = stmt.where(JobRecord.id == only_job_id)
    stmt = stmt.order_by(JobRecord.created_at).limit(1).with_for_update(skip_locked=True)
    record = db.execute(stmt).scalars().first()
    if record is None:
        return None

    if record.status == "running":
        # Stale lease: the previous attempt died before reaching its own
        # except handler (a hard crash, not a raised exception) -- count it
        # as a failed attempt against the same retry budget an explicit
        # failure would consume.
        record.retry_count += 1
        if record.retry_count > max_retries:
            record.status = "dead_letter"
            record.error = "Exceeded max retries after worker crash (lease expired)"
            record.completed_at = now
            record.leased_until = None
            db.commit()
            return None

    record.status = "running"
    record.leased_until = now + timedelta(seconds=lease_seconds)
    if record.started_at is None:
        record.started_at = now
    job_id, job_type, payload, retry_count = (
        record.id,
        record.job_type,
        record.payload or {},
        record.retry_count,
    )
    db.commit()
    return ClaimedJob(job_id=job_id, job_type=job_type, payload=payload, retry_count=retry_count)


def renew_lease(job_id: UUID, *, lease_seconds: float = LEASE_SECONDS) -> None:
    """Extends a claimed job's lease. Called periodically by a heartbeat
    thread running alongside the (possibly long, blocking) work function --
    that thread needs its own session, since the main thread's session is
    busy for the whole duration of the work function call."""
    now = datetime.now(timezone.utc)
    with session_scope() as db:
        db.execute(
            update(JobRecord)
            .where(JobRecord.id == job_id)
            .values(leased_until=now + timedelta(seconds=lease_seconds))
        )


def complete_job(db: Session, job_id: UUID, result: Dict[str, Any]) -> None:
    now = datetime.now(timezone.utc)
    record = db.get(JobRecord, job_id)
    if record is None:
        return
    record.status = "completed"
    record.result = result
    record.completed_at = now
    record.leased_until = None


def fail_or_requeue_job(
    db: Session, job_id: UUID, error: str, *, max_retries: int = MAX_RETRIES
) -> str:
    """Explicit-failure path -- the work function itself raised. Increments
    retry_count and either requeues (QUEUED, eligible for another claim) or
    moves to the terminal DEAD_LETTER state once the budget is exhausted.
    Returns the resulting status, mainly so callers/tests don't need a
    second query to see what happened."""
    now = datetime.now(timezone.utc)
    record = db.get(JobRecord, job_id)
    if record is None:
        return "missing"
    record.retry_count += 1
    record.error = error
    if record.retry_count > max_retries:
        record.status = "dead_letter"
        record.completed_at = now
    else:
        record.status = "queued"
    record.leased_until = None
    return record.status
