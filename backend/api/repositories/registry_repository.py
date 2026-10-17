from typing import List, Optional
from uuid import UUID

from backend.api.repositories.base import BaseRepository
from backend.db.models.registry import Model, Router, RouterVersion


class RouterRepository(BaseRepository[Router]):
    model = Router

    def get_by_name(self, name: str) -> Optional[Router]:
        return self.db.query(Router).filter(Router.name == name).first()


class RouterVersionRepository(BaseRepository[RouterVersion]):
    model = RouterVersion

    def list_for_router(self, router_id: UUID, limit: int = 50) -> List[RouterVersion]:
        return list(
            self.db.query(RouterVersion)
            .filter(RouterVersion.router_id == router_id)
            .order_by(RouterVersion.created_at.desc())
            .limit(limit)
            .all()
        )

    def get_by_training_job_id(self, training_job_id: UUID) -> Optional[RouterVersion]:
        return (
            self.db.query(RouterVersion)
            .filter(RouterVersion.training_job_id == training_job_id)
            .first()
        )


class ModelRepository(BaseRepository[Model]):
    model = Model

    def get_by_name(self, name: str) -> Optional[Model]:
        return self.db.query(Model).filter(Model.name == name).first()
