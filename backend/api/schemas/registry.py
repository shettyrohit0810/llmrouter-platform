from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from backend.db.models.registry import RouterVersion


class RouterEntryResponse(BaseModel):
    id: UUID
    name: str
    class_name: str
    trainable: bool
    status: str
    tags: Optional[List[str]] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RouterEntryListResponse(BaseModel):
    routers: List[RouterEntryResponse]


class ModelEntryResponse(BaseModel):
    id: UUID
    name: str
    provider: Optional[str] = None
    description: Optional[str] = None
    context_limit: Optional[int] = None
    input_price: Optional[float] = None
    output_price: Optional[float] = None
    tags: Optional[List[str]] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ModelEntryListResponse(BaseModel):
    models: List[ModelEntryResponse]


class RouterVersionCreateRequest(BaseModel):
    router_name: str = Field(..., description="Registered router name, e.g. 'knnrouter'")
    version_label: str = Field(..., description="e.g. 'v1', a date, or a commit-ish label")
    checkpoint_path: str
    project_id: Optional[UUID] = Field(
        None, description="Attaches this version to a project; requires Developer+ membership"
    )
    metadata: Optional[Dict[str, Any]] = None


class RouterVersionResponse(BaseModel):
    id: UUID
    router_id: UUID
    project_id: Optional[UUID] = None
    version_label: str
    checkpoint_path: str
    training_job_id: Optional[UUID] = None
    metadata: Optional[Dict[str, Any]] = None
    status: str
    created_at: datetime

    @classmethod
    def from_model(cls, version: "RouterVersion") -> "RouterVersionResponse":
        # Same reason as ExperimentResponse.from_model: the ORM attribute is
        # `metadata_`, not `metadata` (reserved by SQLAlchemy's
        # DeclarativeBase), so this can't be a plain from_attributes mapping.
        return cls(
            id=version.id,
            router_id=version.router_id,
            project_id=version.project_id,
            version_label=version.version_label,
            checkpoint_path=version.checkpoint_path,
            training_job_id=version.training_job_id,
            metadata=version.metadata_,
            status=version.status,
            created_at=version.created_at,
        )


class RouterVersionListResponse(BaseModel):
    versions: List[RouterVersionResponse]
