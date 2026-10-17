"""Experiment table. Schema only, per Milestone 4's scope -- Milestone 8
(Experiment Tracking) implements the service/repository/endpoint layer that
optionally creates one of these per train/benchmark/benchmark_compare/infer
call.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base

VALID_EXPERIMENT_TYPES = ("train", "benchmark", "benchmark_compare", "infer")


class Experiment(Base):
    __tablename__ = "experiments"
    __table_args__ = (
        CheckConstraint(
            f"experiment_type IN {tuple(VALID_EXPERIMENT_TYPES)}", name="valid_experiment_type"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    # Nullable: an experiment can stand alone (a synchronous /route or /infer
    # call that never created a JobRecord) rather than always originate from
    # a background job.
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    experiment_type: Mapped[str] = mapped_column(String, nullable=False)
    router_name: Mapped[str | None] = mapped_column(String, nullable=True)
    router_version: Mapped[str | None] = mapped_column(String, nullable=True)
    model_version: Mapped[str | None] = mapped_column(String, nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # See registry.py's RouterVersion.metadata_ for why this can't be named
    # `metadata` as a Python attribute.
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    cost_estimate: Mapped[float | None] = mapped_column(nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
