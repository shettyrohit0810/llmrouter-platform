# Database Layer

**Status:** Phase 4, Milestone 1. Introduces PostgreSQL, SQLAlchemy, Alembic, connection
management, and the repository abstraction. No domain tables yet — see Milestone 4
(`docs/design.md`) for `users`, `organizations`,
`jobs`, etc.

## Why Sync SQLAlchemy, Not Async

FastAPI route handlers in `backend/` stay `async def` for everything that doesn't touch the
database (matching Phase 3). Handlers that do touch the database use SQLAlchemy's sync API
(`psycopg2` driver) and are declared as regular `def` — FastAPI's own documented pattern for sync
I/O, which Starlette runs in a threadpool so it never blocks the event loop. This avoids
`AsyncSession`'s extra lifecycle rules (no lazy-load outside an active async context, explicit
`await session.refresh()`, etc.) that aren't warranted at this platform's expected scale, and keeps
Alembic's migration story simple (Alembic's own tooling is sync-first).

## Connection Management (`backend/db/session.py`)

- **One `Engine` per process** (`init_engine(database_url)`), created once in `create_app()` and
  reused for the life of the process. `pool_pre_ping=True` so a connection dropped by the database
  (idle timeout, restart) is detected and replaced rather than surfacing as a query error.
- **`session_scope()`** — a context manager yielding a `Session`, committing on success, rolling
  back and re-raising on any exception, always closing. Used directly by code outside FastAPI's
  request cycle (background jobs, from Milestone 7 onward).
- **`get_db()`** — the FastAPI dependency form of the same thing:
  `db: Session = Depends(get_db)`. One session per request, matching the standard FastAPI +
  SQLAlchemy pattern.
- **`check_connection()`** — a cheap real round trip (`SELECT 1`), used by `/health`. Returns
  `False` instead of raising, so the health route can decide the HTTP status rather than the
  database driver's exception type leaking into a 500.

## Repository Layer (`backend/api/repositories/`)

`BaseRepository[ModelType]` (`backend/api/repositories/base.py`) provides `get`, `list`, `create`,
`update`, `delete` against any ORM model. Every entity-specific repository added in later
milestones (`UserRepository`, `JobRepository`, ...) subclasses it and only adds
query methods that don't fit the generic CRUD shape (e.g. `UserRepository.get_by_email`) — this is
what Rule 8 ("database access must be behind service/repository abstractions") and Rule 6 ("never
duplicate business logic") require: route handlers never construct a SQLAlchemy `Session` query
directly, and common CRUD is implemented exactly once.

`tests/test_db.py` unit-tests `BaseRepository` against an in-memory SQLite engine, using a
throwaway `DeclarativeBase`/model defined only in the test file — deliberately **not**
`backend.db.base.Base`, so the test never pollutes the real schema that Alembic's autogenerate
targets.

## Alembic

- `alembic.ini` (repo root) + `backend/db/migrations/` (env, script template, `versions/`).
- `backend/db/migrations/env.py` imports `backend.db.base.Base` and `backend.db.models` (which
  re-exports every ORM model, so importing it registers all tables on `Base.metadata` — this is
  what makes `alembic revision --autogenerate` see the real schema once Milestone 4 adds models).
- **`DATABASE_URL` env var overrides `alembic.ini`'s static `sqlalchemy.url`** — one migration
  setup works unmodified against dev/test/prod.
- **Every migration includes rollback notes in its own docstring** (Rule 5), not a separate
  document — the note travels with the code that needs it.

**Common commands:**

```bash
# Apply all pending migrations
DATABASE_URL=postgresql+psycopg2://llmrouter:llmrouter_dev_password@localhost:5434/llmrouter \
  alembic upgrade head

# Roll back one migration
alembic downgrade -1

# Generate a new migration from model changes (once models exist, Milestone 4+)
alembic revision --autogenerate -m "add users table"

# Check current revision
alembic current
```

**First migration (`5b8775bf946a`, "enable pgcrypto extension"):** enables PostgreSQL's
`pgcrypto` extension so every later table can default its UUID primary key to
`gen_random_uuid()` server-side, rather than generating UUIDs in Python and risking a mismatch
between what the ORM thinks the ID is and what's actually stored. Verified end-to-end in this
environment: `upgrade head` → extension present (`\dx` shows `pgcrypto`) → `downgrade base` →
extension removed → `upgrade head` again → restored. This is also the template every later
migration follows for its own rollback verification.

## Local Development

A dedicated dev PostgreSQL container (separate from any other project's Postgres on this
machine — this environment already had containers bound to ports 5432 and 5433):

```bash
docker run -d --name llmrouter-postgres-dev \
  -e POSTGRES_USER=llmrouter \
  -e POSTGRES_PASSWORD=llmrouter_dev_password \
  -e POSTGRES_DB=llmrouter \
  -p 5434:5432 \
  postgres:16-alpine
```

`BackendConfig.database_url` defaults to
`postgresql+psycopg2://llmrouter:llmrouter_dev_password@localhost:5434/llmrouter`, matching this
container, so no env var is required for local development once it's running. Override with the
`DATABASE_URL` env var for any other target (CI, a different local port, production).

**Test dependency, stated explicitly:** `tests/test_health_db.py`'s
`test_health_ok_when_database_reachable` (and, transitively, every existing test that hits
`/health` — `test_middleware.py`, `test_openapi.py`, `test_openai_compat.py`) now requires this
container (or an equivalent reachable Postgres) to be running, since `/health` performs a real
connectivity check. This mirrors the existing convention of integration tests exercising a real
dependency rather than a mock; the container must be up before running `pytest tests/`.

## Docker Compose

`docker-compose.yml` gained a `postgres` service (named volume for data persistence, healthcheck
via `pg_isready`) and the `backend` service now: depends on `postgres` being healthy before
starting, receives `DATABASE_URL` pointing at the internal Docker network hostname (`postgres`,
not `localhost`), and runs `alembic upgrade head` before `uvicorn` starts (its `command` override —
the modular-monolith equivalent of a migration init-container, without introducing a second
deployable or service). The bare `Dockerfile` `CMD` is unchanged (plain `uvicorn`, for `docker run`
against an already-migrated database).
