from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel

from backend.db.models.audit import AuditLog


class AuditLogResponse(BaseModel):
    id: UUID
    organization_id: Optional[UUID] = None
    project_id: Optional[UUID] = None
    user_id: Optional[UUID] = None
    api_key_id: Optional[UUID] = None
    action: str
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    ip_address: Optional[str] = None
    created_at: datetime

    @classmethod
    def from_model(cls, log: AuditLog) -> "AuditLogResponse":
        # Same reason as ExperimentResponse/RouterVersionResponse: the ORM
        # attribute is `metadata_`, not `metadata` (reserved by
        # DeclarativeBase), so this can't be a plain from_attributes mapping.
        return cls(
            id=log.id,
            organization_id=log.organization_id,
            project_id=log.project_id,
            user_id=log.user_id,
            api_key_id=log.api_key_id,
            action=log.action,
            resource_type=log.resource_type,
            resource_id=log.resource_id,
            metadata=log.metadata_,
            ip_address=log.ip_address,
            created_at=log.created_at,
        )


class AuditLogListResponse(BaseModel):
    logs: List[AuditLogResponse]
