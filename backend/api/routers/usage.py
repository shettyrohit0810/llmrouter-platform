"""Usage analytics endpoints -- read-only, project-scoped, requiring Viewer+
membership via the same require_project_role dependency Milestone 3 built.
Writing happens as a side effect of route/infer/train/benchmark/
benchmark_compare (backend/api/routers/management.py), not here.
"""

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.api.rbac.dependencies import require_project_role
from backend.api.rbac.roles import Role
from backend.api.schemas.usage import (
    UsageRecordListResponse,
    UsageRecordResponse,
    UsageSummaryResponse,
)
from backend.api.services import usage
from backend.db.session import get_db

router = APIRouter(tags=["usage"])


@router.get("/projects/{project_id}/usage", response_model=UsageRecordListResponse)
def list_project_usage(
    project_id: UUID,
    limit: int = 100,
    _membership=Depends(require_project_role(Role.VIEWER)),
    db: Session = Depends(get_db),
):
    records = usage.list_usage_records(db, project_id=project_id, limit=limit)
    return UsageRecordListResponse(records=[UsageRecordResponse.model_validate(r) for r in records])


@router.get("/projects/{project_id}/usage/summary", response_model=UsageSummaryResponse)
def get_project_usage_summary(
    project_id: UUID,
    _membership=Depends(require_project_role(Role.VIEWER)),
    db: Session = Depends(get_db),
):
    return UsageSummaryResponse(**usage.get_usage_summary(db, project_id=project_id))
