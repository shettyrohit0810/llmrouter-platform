from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class RouteRequest(BaseModel):
    router: str = Field(..., description="Registered router name, e.g. 'knnrouter'")
    config_path: str = Field(..., description="Path to the router's YAML config")
    query: str = Field(..., min_length=1)


class RouteResponse(BaseModel):
    success: bool
    query: str
    model_name: Optional[str] = None
    routing_result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class InferRequest(BaseModel):
    router: str
    config_path: str
    query: str = Field(..., min_length=1)
    max_tokens: int = 512
    temperature: float = 0.01
    # Default False, unlike train/benchmark/benchmark_compare: inference is
    # comparatively high-volume/low-value to record individually (per
    # docs/migration/phase3_to_phase4.md's Experiment Persistence section).
    create_experiment: bool = Field(
        False,
        description=(
            "Record an Experiment for this call. Only takes effect for "
            "API-key-authenticated calls whose key has a project."
        ),
    )


class InferResponse(BaseModel):
    success: bool
    query: str
    response: Optional[str] = None
    model_name: Optional[str] = None
    error: Optional[str] = None
    experiment_id: Optional[UUID] = None
