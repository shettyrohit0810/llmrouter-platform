"""Persistent job tables: JobRecord, TrainingJobDetail, BenchmarkResult.

Schema only, per Milestone 4's scope -- Milestone 7 (Persistent Job System)
implements a PostgresJobStore against JobRecord, replacing Phase 3's
in-memory JobStore behind the same Protocol. Named `JobRecord`, not `Job`,
to stay clearly distinct from `backend.api.services.jobs.Job` (Phase 3's
in-memory dataclass) until Milestone 7 reconciles the two.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base

VALID_JOB_STATUSES = ("queued", "running", "completed", "failed", "cancelled", "dead_letter")


class JobRecord(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(f"status IN {tuple(VALID_JOB_STATUSES)}", name="valid_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    # Nullable: a job may be submitted before the caller has a project
    # (unauthenticated Phase 3 clients) -- same transitional pattern as
    # api_keys.project_id.
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    job_type: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued")
    progress: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Parameters needed to actually execute the job (router name, config
    # path, dataset, project-context ids, etc.) -- populated at submit time
    # so the out-of-process worker (backend/worker/) can reconstruct what to
    # do without any in-memory closure; the worker runs in a different
    # process than the one that received the HTTP request.
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    logs: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # A job is actively claimed by a worker only while this is in the
    # future -- NULL means "not currently claimed". A RUNNING job whose
    # lease has expired (its worker died without finishing) is treated as
    # reclaimable, same as a fresh QUEUED job; see backend/worker/queue.py.
    leased_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TrainingJobDetail(Base):
    """1:1 detail row for a JobRecord where job_type == "train"."""

    __tablename__ = "training_job_details"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    router_name: Mapped[str] = mapped_column(String, nullable=False)
    config_path: Mapped[str] = mapped_column(String, nullable=False)
    device: Mapped[str] = mapped_column(String, nullable=False, default="cpu")
    # Filled in on completion once a RouterVersion is recorded (Milestone 9).
    router_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("router_versions.id", ondelete="SET NULL"), nullable=True
    )


class BenchmarkResult(Base):
    """1:1 detail row for a JobRecord where job_type in
    ("benchmark", "benchmark_compare") -- fields mirror
    backend/api/schemas/benchmark.py's BenchmarkResult exactly, per that
    schema's own docstring ("designed so a future phase can persist this to
    PostgreSQL without changing the API shape")."""

    __tablename__ = "benchmark_results"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    router: Mapped[str] = mapped_column(String, nullable=False)
    dataset: Mapped[str] = mapped_column(String, nullable=False)
    num_queries: Mapped[int] = mapped_column(Integer, nullable=False)
    accuracy: Mapped[float] = mapped_column(nullable=False)
    average_latency_seconds: Mapped[float] = mapped_column(nullable=False)
    average_token_usage: Mapped[float] = mapped_column(nullable=False)
    routing_distribution: Mapped[dict] = mapped_column(JSONB, nullable=False)
    failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    evaluation_summary: Mapped[str] = mapped_column(Text, nullable=False)
