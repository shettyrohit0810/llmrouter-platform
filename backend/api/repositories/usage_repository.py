from typing import Any, Dict, List
from uuid import UUID

from sqlalchemy import func

from backend.api.repositories.base import BaseRepository
from backend.db.models.usage import UsageRecord


class UsageRecordRepository(BaseRepository[UsageRecord]):
    model = UsageRecord

    def list_for_project(self, project_id: UUID, limit: int = 100) -> List[UsageRecord]:
        return list(
            self.db.query(UsageRecord)
            .filter(UsageRecord.project_id == project_id)
            .order_by(UsageRecord.created_at.desc())
            .limit(limit)
            .all()
        )

    def summary_for_project(self, project_id: UUID) -> Dict[str, Any]:
        """One aggregate query rather than pulling every row into Python --
        scales with the database, not with request volume."""
        base = self.db.query(UsageRecord).filter(UsageRecord.project_id == project_id)

        totals = base.with_entities(
            func.count(UsageRecord.id),
            func.coalesce(func.sum(UsageRecord.tokens_input), 0),
            func.coalesce(func.sum(UsageRecord.tokens_output), 0),
            func.coalesce(func.avg(UsageRecord.latency_ms), 0.0),
            func.coalesce(func.sum(UsageRecord.cost_estimate), 0.0),
        ).one()
        total_requests, total_tokens_input, total_tokens_output, avg_latency_ms, total_cost = totals

        by_endpoint: Dict[str, int] = {
            row[0]: row[1]
            for row in base.with_entities(UsageRecord.endpoint, func.count(UsageRecord.id))
            .group_by(UsageRecord.endpoint)
            .all()
        }
        by_router: Dict[str, int] = {
            row[0]: row[1]
            for row in base.filter(UsageRecord.router_name.isnot(None))
            .with_entities(UsageRecord.router_name, func.count(UsageRecord.id))
            .group_by(UsageRecord.router_name)
            .all()
        }
        by_model: Dict[str, int] = {
            row[0]: row[1]
            for row in base.filter(UsageRecord.model_name.isnot(None))
            .with_entities(UsageRecord.model_name, func.count(UsageRecord.id))
            .group_by(UsageRecord.model_name)
            .all()
        }

        return {
            "total_requests": total_requests,
            "total_tokens_input": int(total_tokens_input),
            "total_tokens_output": int(total_tokens_output),
            "average_latency_ms": float(avg_latency_ms),
            "total_cost_estimate": float(total_cost),
            "requests_by_endpoint": by_endpoint,
            "requests_by_router": by_router,
            "requests_by_model": by_model,
        }
