"""Declarative base shared by every ORM model in backend/db/models/.

The naming convention is applied so Alembic's autogenerate produces stable,
predictable constraint names across migrations -- without it, SQLAlchemy lets
the database pick names, which differ between runs and make autogenerate
diffs noisy/unreliable.
"""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
