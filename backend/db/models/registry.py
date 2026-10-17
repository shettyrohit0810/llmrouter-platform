"""Model registry tables: Router, RouterVersion, Model.

Schema only, per Milestone 4's scope -- Milestone 9 (Model Registry)
implements the service/repository/endpoint layer on top of these.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base

VALID_ROUTER_STATUSES = ("active", "deprecated", "unsupported")
VALID_ROUTER_VERSION_STATUSES = ("active", "archived")


class Router(Base):
    """Persisted mirror of the CLI's ROUTER_REGISTRY (llmrouter.cli.
    router_inference), with metadata/tags/status the in-code registry
    doesn't carry. Not the source of truth for *what routers exist* --
    backend/api/services/router_registry.py's list_routers() still reads
    the real registry; this table is for the registry-with-metadata view
    Milestone 9 builds (tags, status overrides, version history)."""

    __tablename__ = "routers"
    __table_args__ = (
        CheckConstraint(f"status IN {tuple(VALID_ROUTER_STATUSES)}", name="valid_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    class_name: Mapped[str] = mapped_column(String, nullable=False)
    trainable: Mapped[bool] = mapped_column(nullable=False, default=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    tags: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RouterVersion(Base):
    """A trained checkpoint of a Router -- created when a training job
    completes (Milestone 7/9 wire this up; the column exists now so
    training_job_details.router_version_id has something to reference)."""

    __tablename__ = "router_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    router_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("routers.id", ondelete="CASCADE"), nullable=False
    )
    # Nullable: a version can be organization-shared (no project) or
    # project-specific.
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    version_label: Mapped[str] = mapped_column(String, nullable=False)
    checkpoint_path: Mapped[str] = mapped_column(String, nullable=False)
    training_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    # Python attribute can't be named `metadata` -- that name is reserved by
    # SQLAlchemy's DeclarativeBase for the table MetaData object. Mapped to
    # the actual "metadata" column via the explicit column-name argument.
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(f"status IN {tuple(VALID_ROUTER_VERSION_STATUSES)}", name="valid_status"),
    )


class Model(Base):
    """Candidate LLM registry -- persisted mirror of
    data/example_data/llm_candidates/*.json, with room for tenant-specific
    overrides Milestone 9 may add."""

    __tablename__ = "models"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    provider: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    context_limit: Mapped[int | None] = mapped_column(nullable=True)
    input_price: Mapped[float | None] = mapped_column(nullable=True)
    output_price: Mapped[float | None] = mapped_column(nullable=True)
    tags: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
