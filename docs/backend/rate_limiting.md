# Rate Limiting (Milestone 6)

**Status:** Phase 4, Milestone 6. Builds on `docs/backend/caching.md`'s Redis layer.

## Middleware, Literally This Time

Milestone 3's RBAC needed FastAPI *dependencies* instead of literal ASGI middleware, because
permission checks need a resolved path parameter (`organization_id`, `project_id`) that isn't
available until routing completes. Rate limiting needs only the request's client IP and
`Authorization`/`X-API-Key` headers — both available before routing — so
`backend/api/middleware/rate_limit.py::RateLimitMiddleware` genuinely is plain `BaseHTTPMiddleware`,
applied globally in `create_app()` to every request on both API surfaces (`/api/v1/*` and the
mounted `/v1/*`), matching the spec's "middleware" wording without the RBAC-style reinterpretation.

## Two Checks Per Request

1. **IP-based sliding window** — always applied, `ANONYMOUS_IP_LIMIT` = 100 requests / 60 seconds
   per client IP (`backend/ratelimit/plans.py`). An anti-abuse floor independent of authentication.
2. **Identity-based token bucket** — only applied once an identity is resolved (API key or JWT
   user); sized from the caller's plan tier.

Both share the same 429 response shape (`{"error", "error_type": "rate_limit_exceeded",
"request_id"}` + a `Retry-After` header), written directly as a `JSONResponse` rather than via
`HTTPException` — middleware sits outside the exception-handler layer for this kind of
short-circuit, so constructing the response directly avoids depending on ordering between
`RateLimitMiddleware` and FastAPI's own exception-handling middleware.

## Two Algorithms (`backend/ratelimit/algorithms.py`)

Both are Redis Lua scripts (`redis.Redis.register_script`), not a Python read-check-write
sequence — a plain GET/compute/SET would race under concurrent requests to the same key (two
requests could both read "9 of 10 used" and both be allowed).

- **`SlidingWindowLimiter`** — a Redis sorted set keyed by timestamp; precise (no fixed-window
  boundary burst), used for the IP-based anti-abuse check.
- **`TokenBucketLimiter`** — a Redis hash storing `(tokens, last_refill)`; continuous refill at a
  configured rate, allowing bursts up to capacity then throttling to steady-state. Used for
  plan-tier limits, since "N requests per minute with some burst headroom" is what a plan limit
  means in practice.

## Plan Tiers (`backend/ratelimit/plans.py`)

| Plan | Burst capacity | Steady-state |
|---|---|---|
| Free | 60 | ~60 req/min (1/sec refill) |
| Developer | 600 | ~600 req/min (10/sec refill) |
| Enterprise | 6000 | ~6000 req/min (100/sec refill) |

An unrecognized plan string falls back to Free (`plan_limit()`), never to unlimited.

## Identity Resolution (`backend/ratelimit/identity.py`)

Precedence: `X-API-Key` header → `Authorization: Bearer` JWT → anonymous (IP-only). An invalid or
expired token doesn't raise an auth error here — rate limiting always resolves to *some* identity
(falling back to anonymous) and never blocks a request because credentials were bad; that's the
actual auth dependency's job on routes that require it.

**Plan resolution for an API key:** `api_keys.project_id` → `projects.organization_id` →
`organizations.plan`, cached in `backend/cache/caches.py`'s `session_cache` for 60 seconds (this is
exactly the consumer `docs/backend/caching.md` anticipated for that cache when it was built with no
consumer yet in Milestone 5). A legacy key with no `project_id` (created before Milestone 3) falls
back to Free.

**Plan resolution for a bare JWT:** always Free. A user can belong to multiple organizations with
different plans, and Phase 3's original endpoints aren't project-scoped, so there's no unambiguous
organization to resolve a plan from yet — the same limitation noted in
`docs/backend/authentication.md`.

## Fails Open on Backing-Store Errors

**Bug found and fixed during verification:** the middleware's Redis calls were originally
unguarded — pointing Redis at an unreachable host didn't just make `/health` report `503` (the
intended, correct behavior from Milestone 5), it made *every single request* raise an uncaught
`ConnectionError` and return a generic `500`, including the `/health` request itself trying to
report the outage. Fixed by wrapping identity resolution and both rate-limit checks in one
try/except covering `redis.RedisError` and `sqlalchemy.exc.SQLAlchemyError` (identity resolution
also queries Postgres for API-key lookups) — on either, the middleware logs a warning and lets the
request through unthrottled rather than crashing it. `/health`'s own independent Redis/Postgres
checks are what's supposed to surface an outage; the rate limiter silently degrading instead of
crashing every request is what makes that check meaningful rather than redundant with a flood of
request-level failures. Verified in `tests/test_ratelimit.py::
test_middleware_fails_open_when_redis_unreachable`.

## Test Isolation: a Second Real Flake, Same Root Cause as Milestone 3's

**Bug found and fixed during verification:** the full `tests/` suite failed 17 tests
(across `test_rbac.py`, `test_ratelimit.py`, and `test_health_redis.py`) the first time it ran with
this middleware active globally. Every test in the suite goes through `TestClient`, which presents
the same fixed client IP (`"testclient"`) for every request, and the IP-based sliding-window
counter lives in the same real, persistent Redis container every test shares — so a
request-heavy test running early in the suite consumes quota that a later, completely unrelated
test then gets blamed for exceeding. This is the identical class of bug as Milestone 3's
organization-name collision (shared real backing-service state across tests, not isolated per
test) — same root cause, different backing service. Fixed with an autouse fixture
(`tests/conftest.py::_reset_rate_limits`) that flushes every `ratelimit:*` key before each
test function runs, so every test starts with a clean rate-limit slate regardless of what ran
before it. A real deployment never hits this — genuine traffic from one client is spread over real
time, not compressed into milliseconds the way a test run is.

## Middleware Ordering

`RateLimitMiddleware` is registered between `GZipMiddleware` and `CORSMiddleware` in
`backend/app.py::create_app()` — inside CORS (added before it, so CORS remains outermost) so a
browser's `OPTIONS` preflight request is handled by CORS and never consumes rate-limit quota.

## Testing

`tests/test_ratelimit.py` — unit tests for `plan_limit()`'s fallback behavior; integration
tests (real dev Redis + Postgres containers) for both algorithms' allow/deny/refill/expiry behavior
directly, identity resolution (anonymous/valid-JWT/invalid-JWT), the middleware enforcing a plan's
exact capacity end-to-end through a real `TestClient` request sequence, the uniform 429 response
shape, and the fail-open behavior above.
