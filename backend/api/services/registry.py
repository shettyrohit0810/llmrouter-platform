"""Model registry: persisted routers/router-versions/models, syncing from
the existing CLI registries rather than duplicating what they already know.

`Router`/`Model` rows are upserted from the live in-code registries
(`backend/api/services/router_registry.py`) on every read -- there are only
~20 routers, so re-syncing per request is cheap and means the persisted
table can never drift from what's actually installed. `RouterVersion` rows
are created explicitly (by a completed training job, or manually) since a
version is an event, not a fact that can be re-derived from code.
"""

from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from backend.api.repositories.registry_repository import (
    ModelRepository,
    RouterRepository,
    RouterVersionRepository,
)
from backend.api.services import router_registry
from backend.db.models.registry import Model, Router, RouterVersion


def sync_and_list_routers(db: Session) -> List[Router]:
    live_routers = router_registry.list_routers()
    repo = RouterRepository(db)
    for info in live_routers:
        existing = repo.get_by_name(info.name)
        status = "unsupported" if info.unsupported_reason else "active"
        if existing is None:
            repo.create(
                name=info.name, class_name=info.class_name, trainable=info.trainable, status=status
            )
        elif existing.class_name != info.class_name or existing.status != status:
            repo.update(existing, class_name=info.class_name, status=status)
    return repo.list(limit=200)


def sync_and_list_models(db: Session, llm_data_path: str) -> List[Model]:
    live_models = router_registry.list_models(llm_data_path)
    repo = ModelRepository(db)
    for info in live_models:
        existing = repo.get_by_name(info.name)
        if existing is None:
            repo.create(name=info.name)
    return repo.list(limit=200)


def get_or_create_router(db: Session, *, name: str) -> Router:
    """Ensures a Router row exists even if sync_and_list_routers() hasn't
    run yet -- register_router_version() needs a valid router_id FK."""
    repo = RouterRepository(db)
    existing = repo.get_by_name(name)
    if existing is not None:
        return existing
    live_routers = {r.name: r for r in router_registry.list_routers()}
    info = live_routers.get(name)
    return repo.create(
        name=name,
        class_name=info.class_name if info else "Unknown",
        trainable=info.trainable if info else True,
        status="active",
    )


def register_router_version(
    db: Session,
    *,
    router_name: str,
    version_label: str,
    checkpoint_path: str,
    training_job_id: Optional[UUID] = None,
    project_id: Optional[UUID] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> RouterVersion:
    """Idempotent when `training_job_id` is given: returns the existing
    version instead of creating a second one if this exact job already
    registered one. Needed because the real worker queue (backend/worker/)
    can call this more than once for the same job -- a reclaim after a
    crash, or a retry after a transient failure -- and a job_id has exactly
    one "the training run this job produced" version, not one per attempt."""
    if training_job_id is not None:
        existing = RouterVersionRepository(db).get_by_training_job_id(training_job_id)
        if existing is not None:
            return existing
    router = get_or_create_router(db, name=router_name)
    return RouterVersionRepository(db).create(
        router_id=router.id,
        project_id=project_id,
        version_label=version_label,
        checkpoint_path=checkpoint_path,
        training_job_id=training_job_id,
        metadata_=metadata,
        status="active",
    )


def list_router_versions(db: Session, *, router_name: str, limit: int = 50) -> List[RouterVersion]:
    router = RouterRepository(db).get_by_name(router_name)
    if router is None:
        return []
    return RouterVersionRepository(db).list_for_router(router.id, limit=limit)


def get_router_version(db: Session, version_id: UUID) -> Optional[RouterVersion]:
    return RouterVersionRepository(db).get(version_id)


def archive_router_version(db: Session, version_id: UUID) -> Optional[RouterVersion]:
    repo = RouterVersionRepository(db)
    version = repo.get(version_id)
    if version is None:
        return None
    return repo.update(version, status="archived")
