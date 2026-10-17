from typing import Optional
from uuid import UUID

from backend.api.repositories.base import BaseRepository
from backend.db.models.organization import Organization, OrganizationMember, Project


class OrganizationRepository(BaseRepository[Organization]):
    model = Organization

    def get_by_slug(self, slug: str) -> Optional[Organization]:
        return self.db.query(Organization).filter(Organization.slug == slug).first()


class OrganizationMemberRepository(BaseRepository[OrganizationMember]):
    model = OrganizationMember

    def get_membership(self, organization_id: UUID, user_id: UUID) -> Optional[OrganizationMember]:
        return (
            self.db.query(OrganizationMember)
            .filter(
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.user_id == user_id,
            )
            .first()
        )

    def list_for_organization(self, organization_id: UUID) -> list[OrganizationMember]:
        return list(
            self.db.query(OrganizationMember)
            .filter(OrganizationMember.organization_id == organization_id)
            .all()
        )

    def list_for_user(self, user_id: UUID) -> list[OrganizationMember]:
        return list(
            self.db.query(OrganizationMember).filter(OrganizationMember.user_id == user_id).all()
        )

    def count_owners(self, organization_id: UUID) -> int:
        return (
            self.db.query(OrganizationMember)
            .filter(
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.role == "owner",
            )
            .count()
        )


class ProjectRepository(BaseRepository[Project]):
    model = Project

    def list_for_organization(self, organization_id: UUID) -> list[Project]:
        return list(self.db.query(Project).filter(Project.organization_id == organization_id).all())
