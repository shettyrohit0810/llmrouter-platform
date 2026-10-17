from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=72)
    full_name: Optional[str] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str = Field(..., min_length=8, max_length=72)


class EmailVerificationConfirm(BaseModel):
    token: str


class UserResponse(BaseModel):
    id: UUID
    email: str
    full_name: Optional[str] = None
    is_active: bool
    is_email_verified: bool
    last_login_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class OAuthAuthorizationURLResponse(BaseModel):
    authorization_url: str


class APIKeyCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    # Scope the key to one project. Calls made with a project-scoped key are
    # attributed to that project (usage, experiments, audit trail). Requires at
    # least the Developer role in the project's organization.
    project_id: Optional[UUID] = None


class APIKeyCreatedResponse(BaseModel):
    id: UUID
    name: str
    key_prefix: str
    # The only time the full key is ever returned -- never stored, never
    # retrievable again after this response.
    api_key: str
    project_id: Optional[UUID] = None
    created_at: datetime


class APIKeyResponse(BaseModel):
    id: UUID
    name: str
    key_prefix: str
    project_id: Optional[UUID] = None
    last_used_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    revoked: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class APIKeyListResponse(BaseModel):
    api_keys: list[APIKeyResponse]
