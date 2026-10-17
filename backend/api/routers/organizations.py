"""Organization/Project/RBAC endpoints -- thin wrappers over
backend/api/rbac/service.py. Every route that requires membership or a
minimum role depends on require_org_role/require_project_role
(backend/api/rbac/dependencies.py) -- that dependency is the sole
enforcement point; service.py assumes the caller was already authorized.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.api.auth.dependencies import get_current_user
from backend.api.rbac import service
from backend.api.rbac.dependencies import require_org_role, require_project_role
from backend.api.rbac.exceptions import LastOwnerError, NotAMemberError, UserNotFoundError
from backend.api.rbac.roles import Role
from backend.api.repositories.user_repository import UserRepository
from backend.api.schemas.organizations import (
    MemberAddRequest,
    MemberListResponse,
    MemberResponse,
    MemberRoleUpdateRequest,
    OrganizationCreateRequest,
    OrganizationListResponse,
    OrganizationResponse,
    ProjectCreateRequest,
    ProjectListResponse,
    ProjectResponse,
)
from backend.api.services import audit
from backend.db.models.user import User
from backend.db.session import get_db

router = APIRouter(tags=["organizations"])


def _to_member_response(db: Session, membership) -> MemberResponse:
    member_user = UserRepository(db).get(membership.user_id)
    return MemberResponse(
        user_id=membership.user_id,
        email=member_user.email if member_user else "unknown",
        role=membership.role,
        created_at=membership.created_at,
    )


@router.post("/orgs", response_model=OrganizationResponse, status_code=201)
def create_organization(
    request: OrganizationCreateRequest,
    req: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    org = service.create_organization(db, owner=user, name=request.name)
    audit.record_event(
        db,
        action="org.created",
        user_id=user.id,
        organization_id=org.id,
        resource_type="organization",
        resource_id=str(org.id),
        metadata={"name": org.name},
        ip_address=req.client.host if req.client else None,
    )
    return org


@router.get("/orgs", response_model=OrganizationListResponse)
def list_organizations(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    orgs = service.list_organizations_for_user(db, user=user)
    return OrganizationListResponse(
        organizations=[OrganizationResponse.model_validate(o) for o in orgs]
    )


@router.get("/orgs/{organization_id}", response_model=OrganizationResponse)
def get_organization(
    organization_id: UUID,
    _membership=Depends(require_org_role(Role.VIEWER)),
    db: Session = Depends(get_db),
):
    return service.get_organization(db, organization_id=organization_id)


@router.get("/orgs/{organization_id}/members", response_model=MemberListResponse)
def list_members(
    organization_id: UUID,
    _membership=Depends(require_org_role(Role.VIEWER)),
    db: Session = Depends(get_db),
):
    memberships = service.list_members(db, organization_id=organization_id)
    return MemberListResponse(members=[_to_member_response(db, m) for m in memberships])


@router.post("/orgs/{organization_id}/members", response_model=MemberResponse, status_code=201)
def add_member(
    organization_id: UUID,
    request: MemberAddRequest,
    req: Request,
    actor=Depends(require_org_role(Role.ADMIN)),
    db: Session = Depends(get_db),
):
    try:
        membership = service.add_member(
            db, organization_id=organization_id, email=request.email, role=request.role
        )
    except UserNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"No registered user with email '{request.email}'"
        )
    audit.record_event(
        db,
        action="org.member_added",
        user_id=actor.user_id,
        organization_id=organization_id,
        resource_type="user",
        resource_id=str(membership.user_id),
        metadata={"role": request.role.value},
        ip_address=req.client.host if req.client else None,
    )
    return _to_member_response(db, membership)


@router.patch("/orgs/{organization_id}/members/{user_id}", response_model=MemberResponse)
def update_member_role(
    organization_id: UUID,
    user_id: UUID,
    request: MemberRoleUpdateRequest,
    req: Request,
    actor=Depends(require_org_role(Role.OWNER)),
    db: Session = Depends(get_db),
):
    try:
        membership = service.change_member_role(
            db, organization_id=organization_id, target_user_id=user_id, new_role=request.role
        )
    except NotAMemberError:
        raise HTTPException(status_code=404, detail="Member not found")
    except LastOwnerError:
        raise HTTPException(status_code=409, detail="Cannot demote the last remaining owner")
    audit.record_event(
        db,
        action="org.member_role_changed",
        user_id=actor.user_id,
        organization_id=organization_id,
        resource_type="user",
        resource_id=str(user_id),
        metadata={"role": request.role.value},
        ip_address=req.client.host if req.client else None,
    )
    return _to_member_response(db, membership)


@router.delete("/orgs/{organization_id}/members/{user_id}", status_code=204)
def remove_member(
    organization_id: UUID,
    user_id: UUID,
    req: Request,
    actor=Depends(require_org_role(Role.ADMIN)),
    db: Session = Depends(get_db),
):
    try:
        service.remove_member(db, organization_id=organization_id, target_user_id=user_id)
    except NotAMemberError:
        raise HTTPException(status_code=404, detail="Member not found")
    except LastOwnerError:
        raise HTTPException(status_code=409, detail="Cannot remove the last remaining owner")
    audit.record_event(
        db,
        action="org.member_removed",
        user_id=actor.user_id,
        organization_id=organization_id,
        resource_type="user",
        resource_id=str(user_id),
        ip_address=req.client.host if req.client else None,
    )


@router.post("/orgs/{organization_id}/projects", response_model=ProjectResponse, status_code=201)
def create_project(
    organization_id: UUID,
    request: ProjectCreateRequest,
    req: Request,
    actor=Depends(require_org_role(Role.DEVELOPER)),
    db: Session = Depends(get_db),
):
    project = service.create_project(db, organization_id=organization_id, name=request.name)
    audit.record_event(
        db,
        action="project.created",
        user_id=actor.user_id,
        organization_id=organization_id,
        project_id=project.id,
        resource_type="project",
        resource_id=str(project.id),
        metadata={"name": project.name},
        ip_address=req.client.host if req.client else None,
    )
    return project


@router.get("/orgs/{organization_id}/projects", response_model=ProjectListResponse)
def list_projects(
    organization_id: UUID,
    _membership=Depends(require_org_role(Role.VIEWER)),
    db: Session = Depends(get_db),
):
    projects = service.list_projects(db, organization_id=organization_id)
    return ProjectListResponse(projects=[ProjectResponse.model_validate(p) for p in projects])


@router.get("/projects/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: UUID,
    _membership=Depends(require_project_role(Role.VIEWER)),
    db: Session = Depends(get_db),
):
    return service.get_project(db, project_id=project_id)


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(
    project_id: UUID,
    req: Request,
    actor=Depends(require_project_role(Role.ADMIN)),
    db: Session = Depends(get_db),
):
    service.delete_project(db, project_id=project_id)
    # project_id is intentionally omitted below: delete_project() hard-deletes
    # the row (ProjectRepository.delete(), not a soft-delete flag), so by the
    # time this fires, audit_logs.project_id's FK would reject a reference to
    # an id that no longer exists in `projects`. resource_id (a plain string
    # column, no FK) is what preserves which project this was about.
    audit.record_event(
        db,
        action="project.deleted",
        user_id=actor.user_id,
        organization_id=actor.organization_id,
        resource_type="project",
        resource_id=str(project_id),
        ip_address=req.client.host if req.client else None,
    )
