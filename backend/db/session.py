"""Connection management: one Engine per process, a session factory, and a
FastAPI dependency for handlers that need a database session.

Uses SQLAlchemy's sync API (psycopg2), not the async API. Route handlers that
touch the database are declared as regular `def` (not `async def`) so
Starlette runs them in its threadpool -- this is FastAPI's own documented
pattern for sync database drivers, and keeps the ORM/session lifecycle
(transactions, identity map) simple rather than juggling AsyncSession's extra
rules, which isn't warranted at this platform's scale.
"""

import os
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def init_engine(database_url: str) -> Engine:
    """Create (or return the existing) module-level Engine. Idempotent so
    tests and `create_app()` can both call it safely."""
    global _engine, _SessionLocal
    if _engine is None:
        # Pool sizing is tunable per deployment (DB_POOL_SIZE / DB_MAX_OVERFLOW /
        # DB_POOL_TIMEOUT). The defaults leave headroom over SQLAlchemy's 5+10:
        # request handlers can briefly hold one connection while a service opens
        # another, so a too-small pool turns bursts into timeouts.
        _engine = create_engine(
            database_url,
            pool_pre_ping=True,
            pool_size=int(os.environ.get("DB_POOL_SIZE", "10")),
            max_overflow=int(os.environ.get("DB_MAX_OVERFLOW", "20")),
            pool_timeout=float(os.environ.get("DB_POOL_TIMEOUT", "30")),
        )
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("Database engine not initialized -- call init_engine() first")
    return _engine


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context-manager form for use outside FastAPI's DI (e.g. background jobs)."""
    if _SessionLocal is None:
        raise RuntimeError("Database engine not initialized -- call init_engine() first")
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency: `db: Session = Depends(get_db)`."""
    with session_scope() as session:
        yield session


def check_connection() -> bool:
    """Used by the /health endpoint -- a cheap, real round trip, not just
    'was the engine object constructed'."""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
