# OpenTelemetry & Observability (Milestone 12)

**Status:** Phase 4, Milestone 12. Adds distributed tracing and Prometheus metrics on top of
Milestone 5's structured request logging — none of the three overlap in what they capture.

## Tracing: One Span Per Request, Query, and Redis Command

`backend/observability/tracing.py::configure_tracing()` wires three OpenTelemetry instrumentors:

- `FastAPIInstrumentor` — one span per HTTP request, per app instance (safe to call on every
  `create_app()`, since it's per-instance, not global state).
- `SQLAlchemyInstrumentor` — one span per query, instrumented against the process's single
  `Engine` (`backend.db.session.get_engine()`).
- `RedisInstrumentor` — one span per Redis command (used by both the cache and the rate limiter).

**Zero external infrastructure required to see this work.** `otel_exporter_otlp_endpoint`
defaults to `None`, which prints every span to stdout via `ConsoleSpanExporter`. Setting
`OTEL_EXPORTER_OTLP_ENDPOINT` to a real collector's URL (a local Jaeger, Tempo, or Grafana Alloy
instance) switches to OTLP/HTTP export instead — no code change, just an env var.

**Why `SimpleSpanProcessor` for the console path but `BatchSpanProcessor` for OTLP, not one or
the other everywhere.** This was tried the other way first and reverted after a real failure:
`BatchSpanProcessor` runs a background thread that periodically flushes queued spans. In a test
session (or a process shutting down generally), that thread can wake up *after* stdout has
already been torn down, raising `ValueError: I/O operation on closed file` during teardown —
harmless to correctness, but noisy, and a bad sign to leave in a "verified" build. Printing to
stdout has no network cost to batch in the first place, so `SimpleSpanProcessor` (synchronous,
no background thread) has no real downside there. OTLP export *is* a network call, where batching
genuinely earns its complexity — hence `BatchSpanProcessor` only for that path.

## Metrics: Three Series, Recorded at Their Natural Chokepoints, Not a New Middleware Pass

`backend/observability/metrics.py` defines three Prometheus series and a `GET /metrics` endpoint
(unauthenticated, unversioned — the standard scrape convention, matching `/health`'s own
placement):

| Metric | Type | Labels | Recorded in |
|---|---|---|---|
| `http_requests_total` | Counter | `method`, `path`, `status_code` | `RequestLoggingMiddleware` (Milestone 5) |
| `http_request_duration_seconds` | Histogram | `method`, `path` | `RequestLoggingMiddleware` |
| `job_submissions_total` | Counter | `job_type` | `JobManager.submit()` (Milestone 2/7) |

Both HTTP metrics are recorded inside `RequestLoggingMiddleware.dispatch()`, reusing the timing
it already computes for its own log line — not a second timing pass. `job_submissions_total` is
recorded inside `JobManager.submit()`, the single chokepoint every async job (`train`,
`benchmark`, `benchmark_compare`) already goes through, rather than being duplicated at each of
`management.py`'s three call sites.

**`path` is the route's template, not the raw URL — a real cardinality bug avoided, not a
theoretical one.** `_route_path()` reads `request.scope["route"].path`, falling back to the raw
path only for unmatched routes (404s, which are naturally bounded to "paths someone actually
tried"). Using `request.url.path` directly would give every distinct `project_id`, `job_id`, etc.
its own permanent Prometheus time series — an unbounded-cardinality metric that would eventually
degrade or crash a real Prometheus server. One non-obvious detail found while testing this: a
route's `.path` is relative to the `APIRouter` it was defined on (e.g. `/orgs/{organization_id}`),
not the fully composed path — the `/api/v1` prefix comes from router nesting in `app.py`, not
from each route's own `.path` string. The label reflects that (`/orgs/{organization_id}`, not
`/api/v1/orgs/{organization_id}`) — still fully bounded cardinality, just without the prefix.

## Testing

`tests/test_observability.py` — integration tests against the real dev Postgres/Redis
containers: `/metrics` returns Prometheus text format, a request increments
`http_requests_total`, a path-parameterized route is recorded by its template rather than the raw
UUID (and the raw UUID is confirmed absent from the metrics body), and submitting a training job
increments `job_submissions_total{job_type="train"}` by exactly one.
