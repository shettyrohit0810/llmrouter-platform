"""RBAC business logic: organizations, memberships, projects.

Permission enforcement (membership + minimum role) lives entirely in
backend/api/rbac/dependencies.py's require_org_role/require_project_role,
used by every route in backend/api/routers/organizations.py -- that is the
"middleware enforces permissions" mechanism the spec calls for. Functions
here assume the caller was already authorized and only check resource
existence (OrganizationNotFoundError, ProjectNotFoundError) and
domain invariants that aren't about *who* is asking (UserNotFoundError for
add_member's email lookup, LastOwnerError so an organization can never end
up with zero owners).
"""

import re
from uuid import UUID

from sqlalchemy.orm import Session

from backend.api.rbac.exceptions import (
    LastOwnerError,
    NotAMemberError,
    OrganizationNotFoundError,
    ProjectNotFoundError,
    UserNotFoundError,
)
from backend.api.rbac.roles import Role
from backend.api.repositories.organization_repository import (
    OrganizationMemberRepository,
    OrganizationRepository,
    ProjectRepository,
)
from backend.api.repositories.user_repository import UserRepository
from backend.db.models.organization import Organization, OrganizationMember, Project
from backend.db.models.user import User


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "org"


def _unique_org_slug(db: Session, base: str) -> str:
    repo = OrganizationRepository(db)
    slug = base
    suffix = 1
    while repo.get_by_slug(slug) is not None:
        suffix += 1
        slug = f"{base}-{suffix}"
    return slug


def create_organization(db: Session, *, owner: User, name: str) -> Organization:
    slug = _unique_org_slug(db, _slugify(name))
    org = OrganizationRepository(db).create(name=name, slug=slug, plan="free")
    OrganizationMemberRepository(db).create(
        organization_id=org.id, user_id=owner.id, role=Role.OWNER.value
    )
    return org


def list_organizations_for_user(db: Session, *, user: User) -> list[Organization]:
    memberships = OrganizationMemberRepository(db).list_for_user(user.id)
    org_repo = OrganizationRepository(db)
    orgs = [org_repo.get(m.organization_id) for m in memberships]
    return [o for o in orgs if o is not None]


def get_organization(db: Session, *, organization_id: UUID) -> Organization:
    org = OrganizationRepository(db).get(organization_id)
    if org is None:
        raise OrganizationNotFoundError()
    return org


def list_members(db: Session, *, organization_id: UUID) -> list[OrganizationMember]:
    return OrganizationMemberRepository(db).list_for_organization(organization_id)


def add_member(db: Session, *, organization_id: UUID, email: str, role: Role) -> OrganizationMember:
    target_user = UserRepository(db).get_by_email(email)
    if target_user is None:
        raise UserNotFoundError(email)

    members = OrganizationMemberRepository(db)
    existing = members.get_membership(organization_id, target_user.id)
    if existing is not None:
        return members.update(existing, role=role.value)
    return members.create(organization_id=organization_id, user_id=target_user.id, role=role.value)


def change_member_role(
    db: Session, *, organization_id: UUID, target_user_id: UUID, new_role: Role
) -> OrganizationMember:
    members = OrganizationMemberRepository(db)
    target_membership = members.get_membership(organization_id, target_user_id)
    if target_membership is None:
        raise NotAMemberError()

    if target_membership.role == Role.OWNER.value and new_role != Role.OWNER:
        if members.count_owners(organization_id) <= 1:
            raise LastOwnerError()

    return members.update(target_membership, role=new_role.value)


def remove_member(db: Session, *, organization_id: UUID, target_user_id: UUID) -> None:
    members = OrganizationMemberRepository(db)
    target_membership = members.get_membership(organization_id, target_user_id)
    if target_membership is None:
        raise NotAMemberError()

    if target_membership.role == Role.OWNER.value and members.count_owners(organization_id) <= 1:
        raise LastOwnerError()

    members.delete(target_membership)


def create_project(db: Session, *, organization_id: UUID, name: str) -> Project:
    projects = ProjectRepository(db)
    base_slug = _slugify(name)
    slug = base_slug
    existing_slugs = {p.slug for p in projects.list_for_organization(organization_id)}
    suffix = 1
    while slug in existing_slugs:
        suffix += 1
        slug = f"{base_slug}-{suffix}"

    return projects.create(organization_id=organization_id, name=name, slug=slug)


def list_projects(db: Session, *, organization_id: UUID) -> list[Project]:
    return ProjectRepository(db).list_for_organization(organization_id)


def get_project(db: Session, *, project_id: UUID) -> Project:
    project = ProjectRepository(db).get(project_id)
    if project is None:
        raise ProjectNotFoundError()
    return project


def delete_project(db: Session, *, project_id: UUID) -> None:
    project = get_project(db, project_id=project_id)
    ProjectRepository(db).delete(project)
