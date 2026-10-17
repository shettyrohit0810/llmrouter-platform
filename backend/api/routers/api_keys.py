"""API key management -- requires a logged-in human user (JWT); creating a
key with a key is deliberately not supported."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.api.auth import service
from backend.api.auth.dependencies import get_current_user
from backend.api.auth.exceptions import APIKeyNotFoundError
from backend.api.rbac.roles import Role, meets_minimum
from backend.api.repositories.organization_repository import (
    OrganizationMemberRepository,
    ProjectRepository,
)
from backend.api.schemas.auth import (
    APIKeyCreatedResponse,
    APIKeyCreateRequest,
    APIKeyListResponse,
    APIKeyResponse,
)
from backend.api.services import audit
from backend.db.models.user import User
from backend.db.session import get_db

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


@router.post("", response_model=APIKeyCreatedResponse, status_code=201)
def create_api_key(
    request: APIKeyCreateRequest,
    req: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if request.project_id is not None:
        project = ProjectRepository(db).get(request.project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        membership = OrganizationMemberRepository(db).get_membership(
            project.organization_id, user.id
        )
        if membership is None:
            raise HTTPException(
                status_code=403, detail="Not a member of this project's organization"
            )
        if not meets_minimum(Role(membership.role), Role.DEVELOPER):
            raise HTTPException(status_code=403, detail="Requires 'developer' role or higher")
    raw_key, row = service.create_api_key(
        db, user=user, name=request.name, project_id=request.project_id
    )
    audit.record_event(
        db,
        action="api_key.created",
        user_id=user.id,
        resource_type="api_key",
        resource_id=str(row.id),
        metadata={"name": row.name, "project_id": str(row.project_id) if row.project_id else None},
        ip_address=req.client.host if req.client else None,
    )
    return APIKeyCreatedResponse(
        id=row.id,
        name=row.name,
        key_prefix=row.key_prefix,
        api_key=raw_key,
        project_id=row.project_id,
        created_at=row.created_at,
    )


@router.get("", response_model=APIKeyListResponse)
def list_api_keys(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return APIKeyListResponse(
        api_keys=[APIKeyResponse.model_validate(k) for k in service.list_api_keys(db, user=user)]
    )


@router.delete("/{key_id}", status_code=204)
def revoke_api_key(
    key_id: UUID,
    req: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        service.revoke_api_key(db, user=user, key_id=key_id)
    except APIKeyNotFoundError:
        raise HTTPException(status_code=404, detail="API key not found")
    audit.record_event(
        db,
        action="api_key.revoked",
        user_id=user.id,
        resource_type="api_key",
        resource_id=str(key_id),
        ip_address=req.client.host if req.client else None,
    )
