"""Experiment tracking: optional records created by train/benchmark/
benchmark_compare/infer, only when the caller resolved a project context
(backend/api/dependencies/project_context.py) and asked for one via the
request's `create_experiment` flag.

`router_version` is populated by callers that have one (Milestone 9's
train() handler, once it registers a RouterVersion); `cost_estimate` and
`model_version` are still always None -- there is no cost model or
model-version-tagging system wired up yet. Recording the columns now,
always-None until those exist, avoids another migration later -- the same
"add the column before the feature that fills it" pattern Milestone 4
already used for training_job_details.router_version_id.
"""

from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from backend.api.repositories.experiment_repository import ExperimentRepository
from backend.db.models.experiments import Experiment


def create_experiment(
    db: Session,
    *,
    project_id: UUID,
    job_id: Optional[UUID],
    experiment_type: str,
    router_name: Optional[str] = None,
    router_version: Optional[str] = None,
    metrics: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    duration_seconds: Optional[float] = None,
    created_by: Optional[UUID] = None,
) -> Experiment:
    """Idempotent when `job_id` is given: returns the existing experiment
    instead of creating a duplicate if this job already has one. A job can
    be re-run by the real worker queue (crash reclaim, retry after a
    transient failure); job_id=None calls (e.g. /infer, which has no job)
    are exempt -- multiple standalone experiments with no job are expected
    and legitimate, not duplicates."""
    if job_id is not None:
        existing = ExperimentRepository(db).get_for_job(job_id)
        if existing is not None:
            return existing
    return ExperimentRepository(db).create(
        project_id=project_id,
        job_id=job_id,
        experiment_type=experiment_type,
        router_name=router_name,
        router_version=router_version,
        model_version=None,
        metrics=metrics,
        metadata_=metadata,
        cost_estimate=None,
        duration_seconds=duration_seconds,
        created_by=created_by,
    )


def get_experiment_for_job(db: Session, job_id: UUID) -> Optional[Experiment]:
    return ExperimentRepository(db).get_for_job(job_id)


def get_experiment(db: Session, experiment_id: UUID) -> Optional[Experiment]:
    return ExperimentRepository(db).get(experiment_id)


def list_experiments_for_project(
    db: Session, *, project_id: UUID, limit: int = 50
) -> List[Experiment]:
    return ExperimentRepository(db).list_for_project(project_id, limit=limit)
