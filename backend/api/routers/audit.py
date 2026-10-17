"""Audit log read endpoints -- Admin+ only, since a log of who did what
(including other members' logins and permission changes) is more sensitive
than the Viewer-readable resources (experiments, usage) Milestones 8/10
exposed to any project member.
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.api.rbac.dependencies import require_org_role
from backend.api.rbac.roles import Role
from backend.api.schemas.audit import AuditLogListResponse, AuditLogResponse
from backend.api.services import audit
from backend.db.session import get_db

router = APIRouter(tags=["audit"])


@router.get("/orgs/{organization_id}/audit-logs", response_model=AuditLogListResponse)
def list_organization_audit_logs(
    organization_id: UUID,
    action: Optional[str] = None,
    resource_type: Optional[str] = None,
    user_id: Optional[UUID] = None,
    limit: int = 100,
    _membership=Depends(require_org_role(Role.ADMIN)),
    db: Session = Depends(get_db),
):
    logs = audit.list_audit_logs_for_organization(
        db,
        organization_id=organization_id,
        action=action,
        resource_type=resource_type,
        user_id=user_id,
        limit=limit,
    )
    return AuditLogListResponse(logs=[AuditLogResponse.from_model(log) for log in logs])
