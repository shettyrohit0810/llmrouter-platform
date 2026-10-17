"""Permission-enforcing dependencies.

The spec calls for "middleware" enforcing permissions; true ASGI middleware
runs before routing resolves path parameters, so it cannot know which
organization/project a request targets without re-implementing routing
itself. FastAPI's own recommended mechanism for per-resource authorization is
dependency injection bound to a path parameter -- that's what's implemented
here, the same pragmatic interpretation Phase 3 used for "one FastAPI
application" via app.mount(). Every /api/v1/orgs/* and /api/v1/projects/*
route that needs a role check depends on one of these instead of checking
membership/role inline.
"""

from uuid import UUID

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from backend.api.auth.dependencies import get_current_user
from backend.api.rbac.exceptions import (
    InsufficientRoleError,
    NotAMemberError,
    OrganizationNotFoundError,
    ProjectNotFoundError,
)
from backend.api.rbac.roles import Role, meets_minimum
from backend.api.repositories.organization_repository import (
    OrganizationMemberRepository,
    OrganizationRepository,
    ProjectRepository,
)
from backend.db.models.organization import OrganizationMember
from backend.db.models.user import User
from backend.db.session import get_db


def _membership_or_404(db: Session, *, user: User, organization_id: UUID) -> OrganizationMember:
    if OrganizationRepository(db).get(organization_id) is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    membership = OrganizationMemberRepository(db).get_membership(organization_id, user.id)
    if membership is None:
        raise HTTPException(status_code=403, detail="Not a member of this organization")
    return membership


def require_org_role(minimum: Role):
    """`Depends(require_org_role(Role.ADMIN))` on a route with an
    `organization_id` path parameter -- 404 if the org doesn't exist, 403 if
    the caller isn't a member or doesn't meet the minimum role."""

    def dependency(
        organization_id: UUID,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> OrganizationMember:
        membership = _membership_or_404(db, user=user, organization_id=organization_id)
        if not meets_minimum(Role(membership.role), minimum):
            raise HTTPException(
                status_code=403, detail=f"Requires '{minimum.value}' role or higher"
            )
        return membership

    return dependency


def require_project_role(minimum: Role):
    """Same as require_org_role, but resolves the owning organization from a
    `project_id` path parameter first."""

    def dependency(
        project_id: UUID,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> OrganizationMember:
        project = ProjectRepository(db).get(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        membership = _membership_or_404(db, user=user, organization_id=project.organization_id)
        if not meets_minimum(Role(membership.role), minimum):
            raise HTTPException(
                status_code=403, detail=f"Requires '{minimum.value}' role or higher"
            )
        return membership

    return dependency


# Re-exported so callers importing from this module don't also need
# backend.api.rbac.exceptions for the (rare) case they call the service layer
# directly instead of going through a route dependency.
__all__ = [
    "require_org_role",
    "require_project_role",
    "InsufficientRoleError",
    "NotAMemberError",
    "OrganizationNotFoundError",
    "ProjectNotFoundError",
]
