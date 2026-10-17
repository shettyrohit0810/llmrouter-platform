from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class BenchmarkRequest(BaseModel):
    router: str
    config_path: str = Field(..., description="Router's test-time YAML config")
    dataset: str = Field("default", description="Task/dataset filter; 'default' = all example data")
    sample_size: Optional[int] = Field(
        None, description="Cap on number of test queries evaluated; None = all"
    )
    create_experiment: bool = Field(
        True,
        description=(
            "Record an Experiment for this run. Only takes effect for "
            "API-key-authenticated calls whose key has a project -- ignored "
            "(no experiment created) for anonymous or JWT-only calls."
        ),
    )


class BenchmarkCompareRequest(BaseModel):
    routers: List[str]
    config_paths: Dict[str, str] = Field(
        ..., description="router name -> its test-time YAML config path"
    )
    dataset: str = "default"
    sample_size: Optional[int] = None
    create_experiment: bool = True


class BenchmarkResult(BaseModel):
    """Structured result for a single router's benchmark run. Deliberately
    flat/JSON-serializable so a future phase can persist this to PostgreSQL
    without changing the API shape (per explicit instruction)."""

    router: str
    dataset: str
    num_queries: int
    accuracy: float
    average_latency_seconds: float
    average_token_usage: float
    routing_distribution: Dict[str, int]
    failures: int
    evaluation_summary: str


class BenchmarkResponse(BaseModel):
    job_id: str
    status: str = "queued"


class BenchmarkCompareResult(BaseModel):
    leaderboard: List[BenchmarkResult]
    ranking: List[str] = Field(..., description="Router names, best accuracy first")
