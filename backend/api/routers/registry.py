"""Model registry endpoints. Reading (routers/models/versions) is available
to any authenticated user -- this is shared platform metadata, not
tenant-private data, the same way Phase 3's /routers and /models were
unauthenticated-readable. Writing a project-scoped version requires
Developer+ (create) / Admin+ (archive) membership in that project, checked
inline since the project_id comes from the request body, not a path
parameter that require_project_role can bind to.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.api.auth.dependencies import get_current_user
from backend.api.rbac.roles import Role, meets_minimum
from backend.api.repositories.organization_repository import (
    OrganizationMemberRepository,
    ProjectRepository,
)
from backend.api.schemas.registry import (
    ModelEntryListResponse,
    ModelEntryResponse,
    RouterEntryListResponse,
    RouterEntryResponse,
    RouterVersionCreateRequest,
    RouterVersionListResponse,
    RouterVersionResponse,
)
from backend.api.services import registry
from backend.db.models.user import User
from backend.db.session import get_db

router = APIRouter(prefix="/registry", tags=["registry"])


def _require_project_role(db: Session, user: User, project_id: UUID, minimum: Role) -> None:
    project = ProjectRepository(db).get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    membership = OrganizationMemberRepository(db).get_membership(project.organization_id, user.id)
    if membership is None:
        raise HTTPException(status_code=403, detail="Not a member of this project's organization")
    if not meets_minimum(Role(membership.role), minimum):
        raise HTTPException(status_code=403, detail=f"Requires '{minimum.value}' role or higher")


@router.get("/routers", response_model=RouterEntryListResponse)
def list_routers(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    routers = registry.sync_and_list_routers(db)
    return RouterEntryListResponse(routers=[RouterEntryResponse.model_validate(r) for r in routers])


@router.get("/models", response_model=ModelEntryListResponse)
def list_models(
    llm_data_path: str = Query("data/sample/llm_candidates.json"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    models = registry.sync_and_list_models(db, llm_data_path)
    return ModelEntryListResponse(models=[ModelEntryResponse.model_validate(m) for m in models])


@router.post("/router-versions", response_model=RouterVersionResponse, status_code=201)
def create_router_version(
    request: RouterVersionCreateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if request.project_id is not None:
        _require_project_role(db, user, request.project_id, Role.DEVELOPER)

    version = registry.register_router_version(
        db,
        router_name=request.router_name,
        version_label=request.version_label,
        checkpoint_path=request.checkpoint_path,
        project_id=request.project_id,
        metadata=request.metadata,
    )
    return RouterVersionResponse.from_model(version)


@router.get("/router-versions", response_model=RouterVersionListResponse)
def list_router_versions(
    router_name: str,
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    versions = registry.list_router_versions(db, router_name=router_name, limit=limit)
    return RouterVersionListResponse(
        versions=[RouterVersionResponse.from_model(v) for v in versions]
    )


@router.get("/router-versions/{version_id}", response_model=RouterVersionResponse)
def get_router_version(
    version_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    version = registry.get_router_version(db, version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Router version not found")
    return RouterVersionResponse.from_model(version)


@router.post("/router-versions/{version_id}/archive", response_model=RouterVersionResponse)
def archive_router_version(
    version_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    version = registry.get_router_version(db, version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Router version not found")
    if version.project_id is not None:
        _require_project_role(db, user, version.project_id, Role.ADMIN)

    archived = registry.archive_router_version(db, version_id)
    if archived is None:
        # Existence was already confirmed above -- only reachable via a
        # concurrent delete between the two calls, not the common path.
        raise HTTPException(status_code=404, detail="Router version not found")
    return RouterVersionResponse.from_model(archived)
