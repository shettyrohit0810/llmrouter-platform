from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel


class JobResponse(BaseModel):
    job_id: str
    job_type: str
    status: str
    created_at: float
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    progress: Optional[int] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    # Populated (Milestone 8) when this job created an Experiment record --
    # only possible for API-key-authenticated calls whose key has a project
    # (see backend/api/dependencies/project_context.py). None otherwise; not
    # a new required field, so no existing client parsing this response breaks.
    experiment_id: Optional[UUID] = None


class JobListResponse(BaseModel):
    jobs: List[JobResponse]
