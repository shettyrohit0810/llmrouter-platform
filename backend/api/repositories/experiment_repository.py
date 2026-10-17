from typing import List, Optional
from uuid import UUID

from backend.api.repositories.base import BaseRepository
from backend.db.models.experiments import Experiment


class ExperimentRepository(BaseRepository[Experiment]):
    model = Experiment

    def list_for_project(self, project_id: UUID, limit: int = 50) -> List[Experiment]:
        return list(
            self.db.query(Experiment)
            .filter(Experiment.project_id == project_id)
            .order_by(Experiment.created_at.desc())
            .limit(limit)
            .all()
        )

    def get_for_job(self, job_id: UUID) -> Optional[Experiment]:
        return self.db.query(Experiment).filter(Experiment.job_id == job_id).first()
