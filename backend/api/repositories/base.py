"""Generic repository base class.

Every entity-specific repository (UserRepository, JobRepository, etc., added
in later Phase 4 milestones as their models land) subclasses this instead of
handlers touching `Session`/ORM models directly -- this is the abstraction
Rule 8 ("Database access must be behind service/repository abstractions")
requires. Common CRUD lives here once rather than being re-implemented per
entity (Rule 6, "never duplicate business logic").
"""

from typing import Generic, List, Optional, Type, TypeVar
from uuid import UUID

from sqlalchemy.orm import Session

from backend.db.base import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    model: Type[ModelType]

    def __init__(self, db: Session):
        self.db = db

    def get(self, id: UUID) -> Optional[ModelType]:
        return self.db.get(self.model, id)

    def list(self, limit: int = 50, offset: int = 0) -> List[ModelType]:
        return list(self.db.query(self.model).limit(limit).offset(offset).all())

    def create(self, **fields) -> ModelType:
        obj = self.model(**fields)
        self.db.add(obj)
        self.db.flush()
        return obj

    def update(self, obj: ModelType, **fields) -> ModelType:
        for key, value in fields.items():
            setattr(obj, key, value)
        self.db.flush()
        return obj

    def delete(self, obj: ModelType) -> None:
        self.db.delete(obj)
        self.db.flush()
