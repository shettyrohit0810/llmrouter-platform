"""Shared Pydantic models used across multiple endpoints."""

from typing import Optional

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """Uniform error shape for every non-2xx response from /api/v1/*.
    Never includes a raw traceback (Milestone 6 enforces this at the
    exception-handler level; this schema is the contract that enforces it
    can't accidentally be added back)."""

    error: str = Field(..., description="Human-readable error message")
    error_type: str = Field(..., description="Short machine-readable error category")
    request_id: Optional[str] = Field(None, description="Correlates with logged request ID")
