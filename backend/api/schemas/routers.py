from typing import List, Optional

from pydantic import BaseModel


class RouterInfo(BaseModel):
    name: str
    class_name: str
    trainable: bool
    unsupported_reason: Optional[str] = None


class RouterListResponse(BaseModel):
    routers: List[RouterInfo]


class ModelInfo(BaseModel):
    name: str
    size: Optional[str] = None
    service: Optional[str] = None


class ModelListResponse(BaseModel):
    models: List[ModelInfo]
