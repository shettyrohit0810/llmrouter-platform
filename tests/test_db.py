"""Unit tests for BaseRepository against an in-memory SQLite engine -- fast,
no external dependency, isolated from the app's real Base.metadata (uses its
own DeclarativeBase/MetaData so it never pollutes Alembic's autogenerate
target)."""

import uuid

import pytest
from sqlalchemy import Column, String, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from backend.api.repositories.base import BaseRepository


class _ScratchBase(DeclarativeBase):
    pass


class _Widget(_ScratchBase):
    __tablename__ = "test_widgets"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)


class WidgetRepository(BaseRepository):
    model = _Widget


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    _ScratchBase.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def test_create_and_get(db_session):
    repo = WidgetRepository(db_session)
    widget = repo.create(id=str(uuid.uuid4()), name="alpha")
    fetched = repo.get(widget.id)
    assert fetched is not None
    assert fetched.name == "alpha"


def test_get_missing_returns_none(db_session):
    repo = WidgetRepository(db_session)
    assert repo.get(str(uuid.uuid4())) is None


def test_list_respects_limit(db_session):
    repo = WidgetRepository(db_session)
    for i in range(5):
        repo.create(id=str(uuid.uuid4()), name=f"item-{i}")
    assert len(repo.list(limit=3)) == 3
    assert len(repo.list(limit=50)) == 5


def test_update_mutates_fields(db_session):
    repo = WidgetRepository(db_session)
    widget = repo.create(id=str(uuid.uuid4()), name="before")
    repo.update(widget, name="after")
    assert repo.get(widget.id).name == "after"


def test_delete_removes_row(db_session):
    repo = WidgetRepository(db_session)
    widget = repo.create(id=str(uuid.uuid4()), name="temp")
    repo.delete(widget)
    assert repo.get(widget.id) is None
