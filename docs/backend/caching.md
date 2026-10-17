# Redis Caching Layer (Milestone 5)

**Status:** Phase 4, Milestone 5. Introduces Redis alongside PostgreSQL as a second backing
service — for data that is short-lived, high-write-volume, or doesn't need durability, per
`docs/design.md`'s rationale ("using PostgreSQL for these would be correct but
slower and would add write pressure to the system of record").

## Connection Management (`backend/cache/client.py`)

Mirrors `backend/db/session.py`'s pattern exactly: one client per process (`init_redis(url)`,
idempotent), `get_redis()` to fetch it, `check_connection()` doing a real `PING` for `/health`
rather than just confirming the client object exists. `/health` now checks both PostgreSQL and
Redis, returning `503` if either is unreachable (extends Milestone 1's DB-only check).

## Generic Cache (`backend/cache/namespace.py`)

`CacheNamespace(prefix, default_ttl_seconds)` — `get`/`set`/`delete`/`exists`/`get_or_set`, all
keys prefixed so different callers never collide even if they happen to pick the same raw key
(verified in `tests/test_cache.py::test_cache_namespaces_do_not_collide`). Values are
JSON-serialized; `get_or_set(key, compute, ttl)` only calls `compute()` on a cache miss.

## Named Caches (`backend/cache/caches.py`)

| Cache | Prefix | Default TTL | Future consumer |
|---|---|---|---|
| `session_cache` | `session:` | 15 min | Milestone 6 (rate limiting), Milestone 13 (dashboard) |
| `job_cache` | `job:` | 30s | Milestone 7 (reduce Postgres load for job-status polling) |
| `embedding_cache` | `embedding:` | 24h | Query embeddings never change for identical input |
| `prediction_cache` | `prediction:` | 5 min | Routing decisions — short TTL since retraining changes them |

**None of these are wired into a hot path yet** — Milestone 5's scope is the caching
infrastructure itself, matching Milestone 1's "zero behavior change" stance for the database layer
(and Milestone 2's Job/JobStore precedent from Phase 3: build the complete, tested abstraction
before its first real consumer arrives). `backend/cache/keys.py::stable_key(*parts)` exists for
callers whose natural key is a tuple (query + router name + config path, query + embedding model)
rather than a single identifier — a unit-separator join, not naive string concatenation, so
`stable_key("a", "bc") != stable_key("ab", "c")`.

## Local Development

```bash
docker run -d --name llmrouter-redis-dev -p 6380:6379 redis:7-alpine
```

`BackendConfig.redis_url` defaults to `redis://localhost:6380/0`, matching this container (port
6380 chosen because 6379 was already occupied by an unrelated project on this machine — same
situation Milestone 1 hit with PostgreSQL's default port). Override via `REDIS_URL`.

## Docker Compose

`docker-compose.yml` gained a `redis` service (named volume, `redis-cli ping` healthcheck); the
`backend` service now also depends on `redis` being healthy before starting, and receives
`REDIS_URL` pointing at the internal Docker network hostname.

## Testing

- `tests/test_cache.py` — `stable_key` unit tests (no dependency), integration tests
  against the real dev Redis container for connectivity, generic get/set/delete, namespace
  isolation, `get_or_set` miss/hit behavior, and TTL application.
- `tests/test_health_redis.py` — mirrors `tests/test_health_db.py`'s pattern:
  `check_connection()` returns `False` (not an exception) for an unreachable Redis, and `/health`
  returns `503` in that case.
