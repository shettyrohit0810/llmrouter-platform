from typing import List, Optional
from uuid import UUID

from backend.api.repositories.base import BaseRepository
from backend.db.models.audit import AuditLog


class AuditLogRepository(BaseRepository[AuditLog]):
    model = AuditLog

    def list_for_organization(
        self,
        organization_id: UUID,
        *,
        action: Optional[str] = None,
        resource_type: Optional[str] = None,
        user_id: Optional[UUID] = None,
        limit: int = 100,
    ) -> List[AuditLog]:
        query = self.db.query(AuditLog).filter(AuditLog.organization_id == organization_id)
        if action is not None:
            query = query.filter(AuditLog.action == action)
        if resource_type is not None:
            query = query.filter(AuditLog.resource_type == resource_type)
        if user_id is not None:
            query = query.filter(AuditLog.user_id == user_id)
        return list(query.order_by(AuditLog.created_at.desc()).limit(limit).all())
