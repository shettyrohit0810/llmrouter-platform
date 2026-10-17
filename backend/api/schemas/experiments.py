from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel

if TYPE_CHECKING:
    from backend.db.models.experiments import Experiment


class ExperimentResponse(BaseModel):
    id: UUID
    project_id: UUID
    job_id: Optional[UUID] = None
    experiment_type: str
    router_name: Optional[str] = None
    router_version: Optional[str] = None
    model_version: Optional[str] = None
    metrics: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    cost_estimate: Optional[float] = None
    duration_seconds: Optional[float] = None
    created_by: Optional[UUID] = None
    created_at: datetime

    @classmethod
    def from_model(cls, experiment: "Experiment") -> "ExperimentResponse":
        # Not `model_validate(experiment, from_attributes=True)`: the ORM's
        # Python attribute is `metadata_` (see Experiment's own docstring for
        # why), which doesn't auto-map to this schema's `metadata` field.
        return cls(
            id=experiment.id,
            project_id=experiment.project_id,
            job_id=experiment.job_id,
            experiment_type=experiment.experiment_type,
            router_name=experiment.router_name,
            router_version=experiment.router_version,
            model_version=experiment.model_version,
            metrics=experiment.metrics,
            metadata=experiment.metadata_,
            cost_estimate=experiment.cost_estimate,
            duration_seconds=experiment.duration_seconds,
            created_by=experiment.created_by,
            created_at=experiment.created_at,
        )


class ExperimentListResponse(BaseModel):
    experiments: List[ExperimentResponse]
