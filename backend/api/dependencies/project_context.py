"""Resolves an optional project context from an API key.

Used by Milestone 8 (Experiment Tracking) to decide whether a train/
benchmark/benchmark_compare/infer call has a project to attach an
Experiment record to. Deliberately optional and API-key-only: a bare JWT
user has no unambiguous project (the same limitation
backend/ratelimit/identity.py hit resolving a plan tier -- a user can
belong to several organizations/projects, and Phase 3's original endpoints
aren't project-scoped), so experiment tracking only activates for
API-key-authenticated calls whose key has a project_id, never for
anonymous or JWT-only calls. This mirrors
docs/migration/phase3_to_phase4.md's stated design exactly: "gain an
optional authenticated identity ... which, when present, scopes the
resulting job/experiment/usage record to a project ... when absent, these
endpoints behave exactly as they did in Phase 3."
"""

from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from backend.api.auth.security import hash_token
from backend.db.models.organization import Project
from backend.db.models.user import APIKey
from backend.db.session import get_db


@dataclass
class ProjectContext:
    project_id: UUID
    organization_id: UUID
    api_key_id: UUID
    user_id: Optional[UUID]


def get_optional_project_context(
    x_api_key: Optional[str] = Header(None), db: Session = Depends(get_db)
) -> Optional[ProjectContext]:
    if not x_api_key:
        return None
    key_row = db.query(APIKey).filter(APIKey.key_hash == hash_token(x_api_key)).first()
    if key_row is None or key_row.revoked or key_row.project_id is None:
        return None
    project = db.get(Project, key_row.project_id)
    if project is None:
        return None
    return ProjectContext(
        project_id=key_row.project_id,
        organization_id=project.organization_id,
        api_key_id=key_row.id,
        user_id=key_row.created_by,
    )
