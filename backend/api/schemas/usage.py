from datetime import datetime
from typing import Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel


class UsageRecordResponse(BaseModel):
    id: UUID
    project_id: UUID
    api_key_id: Optional[UUID] = None
    user_id: Optional[UUID] = None
    endpoint: str
    router_name: Optional[str] = None
    model_name: Optional[str] = None
    latency_ms: float
    tokens_input: Optional[int] = None
    tokens_output: Optional[int] = None
    cost_estimate: Optional[float] = None
    status_code: int
    created_at: datetime

    model_config = {"from_attributes": True}


class UsageRecordListResponse(BaseModel):
    records: List[UsageRecordResponse]


class UsageSummaryResponse(BaseModel):
    total_requests: int
    total_tokens_input: int
    total_tokens_output: int
    average_latency_ms: float
    total_cost_estimate: float
    requests_by_endpoint: Dict[str, int]
    requests_by_router: Dict[str, int]
    requests_by_model: Dict[str, int]
