from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from backend.api.rbac.roles import Role


class OrganizationCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)


class OrganizationResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    plan: str
    created_at: datetime

    model_config = {"from_attributes": True}


class OrganizationListResponse(BaseModel):
    organizations: list[OrganizationResponse]


class MemberAddRequest(BaseModel):
    email: EmailStr
    role: Role = Role.VIEWER


class MemberRoleUpdateRequest(BaseModel):
    role: Role


class MemberResponse(BaseModel):
    user_id: UUID
    email: str
    role: str
    created_at: datetime


class MemberListResponse(BaseModel):
    members: list[MemberResponse]


class ProjectCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)


class ProjectResponse(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    slug: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ProjectListResponse(BaseModel):
    projects: list[ProjectResponse]
