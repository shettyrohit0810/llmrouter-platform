from pydantic import BaseModel, Field


class TrainRequest(BaseModel):
    router: str = Field(..., description="Registered, trainable router name")
    config_path: str = Field(..., description="Path to the training YAML config")
    device: str = Field("cpu", pattern="^(cpu|cuda|auto)$")
    create_experiment: bool = Field(
        True,
        description=(
            "Record an Experiment for this run. Only takes effect for "
            "API-key-authenticated calls whose key has a project -- ignored "
            "(no experiment created) for anonymous or JWT-only calls."
        ),
    )


class TrainAcceptedResponse(BaseModel):
    job_id: str
    status: str = "queued"
