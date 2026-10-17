"""Experiment browsing endpoints. Creation happens as a side effect of
train/benchmark/benchmark_compare/infer (backend/api/routers/management.py)
-- these are the read-side, requiring org membership via the same
require_org_role/require_project_role dependencies Milestone 3's RBAC
endpoints use.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.api.auth.dependencies import get_current_user
from backend.api.rbac.dependencies import require_project_role
from backend.api.rbac.roles import Role
from backend.api.repositories.organization_repository import (
    OrganizationMemberRepository,
    ProjectRepository,
)
from backend.api.schemas.experiments import ExperimentListResponse, ExperimentResponse
from backend.api.services import experiments
from backend.db.models.user import User
from backend.db.session import get_db

router = APIRouter(tags=["experiments"])


@router.get("/projects/{project_id}/experiments", response_model=ExperimentListResponse)
def list_project_experiments(
    project_id: UUID,
    limit: int = 50,
    _membership=Depends(require_project_role(Role.VIEWER)),
    db: Session = Depends(get_db),
):
    records = experiments.list_experiments_for_project(db, project_id=project_id, limit=limit)
    return ExperimentListResponse(experiments=[ExperimentResponse.from_model(e) for e in records])


@router.get("/experiments/{experiment_id}", response_model=ExperimentResponse)
def get_experiment(
    experiment_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    experiment = experiments.get_experiment(db, experiment_id)
    if experiment is None:
        raise HTTPException(status_code=404, detail="Experiment not found")

    project = ProjectRepository(db).get(experiment.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    membership = OrganizationMemberRepository(db).get_membership(project.organization_id, user.id)
    if membership is None:
        raise HTTPException(status_code=403, detail="Not a member of this project's organization")

    return ExperimentResponse.from_model(experiment)
