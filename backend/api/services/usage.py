"""Usage analytics: one UsageRecord per tracked request, only when the
caller resolved a project context (backend/api/dependencies/
project_context.py) -- the same API-key-only limitation Milestone 8's
experiment tracking has, since usage_records.organization_id/project_id
are NOT NULL and there's no unambiguous project for a bare JWT or
anonymous call.

`cost_estimate` is always None -- there is no pricing/cost model wired up
yet (Model.input_price/output_price exist in the registry schema since
Milestone 4 but nothing computes a cost from them). Recording the column
now, always-None until a cost pass exists, is the same pattern Milestones
8/9 already used for their own always-None fields.
"""

from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from backend.api.repositories.usage_repository import UsageRecordRepository
from backend.db.models.usage import UsageRecord


def record_usage(
    db: Session,
    *,
    organization_id: UUID,
    project_id: UUID,
    api_key_id: Optional[UUID],
    user_id: Optional[UUID],
    endpoint: str,
    router_name: Optional[str] = None,
    model_name: Optional[str] = None,
    latency_ms: float,
    tokens_input: Optional[int] = None,
    tokens_output: Optional[int] = None,
    status_code: int,
) -> UsageRecord:
    return UsageRecordRepository(db).create(
        organization_id=organization_id,
        project_id=project_id,
        api_key_id=api_key_id,
        user_id=user_id,
        endpoint=endpoint,
        router_name=router_name,
        model_name=model_name,
        latency_ms=latency_ms,
        tokens_input=tokens_input,
        tokens_output=tokens_output,
        cost_estimate=None,
        status_code=status_code,
    )


def list_usage_records(db: Session, *, project_id: UUID, limit: int = 100) -> List[UsageRecord]:
    return UsageRecordRepository(db).list_for_project(project_id, limit=limit)


def get_usage_summary(db: Session, *, project_id: UUID) -> dict:
    return UsageRecordRepository(db).summary_for_project(project_id)
