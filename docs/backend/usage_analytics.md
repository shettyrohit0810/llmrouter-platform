# Usage Analytics (Milestone 10)

**Status:** Phase 4, Milestone 10. Read side over the `usage_records` table (Milestone 4,
schema-only); this milestone adds the write path and the reporting endpoints.

## One Record Per Tracked Request, Same Opt-In Boundary as Milestones 8/9

`usage_records.organization_id`/`project_id` are `NOT NULL`, so a row can only be written when the
request resolved a `ProjectContext` (`backend/api/dependencies/project_context.py`) — i.e. the
caller authenticated with a project-scoped API key. A bare JWT user or an anonymous call to
`/api/v1/route` still works exactly as in Phase 3 (backward compatibility preserved), it simply
produces no usage record, because there is no unambiguous project to attach it to. This is the same
limitation Milestone 8's experiment tracking and Milestone 9's registry sync already accepted.

`_record_usage_safe()` (`backend/api/routers/management.py`) is the single call site all five
endpoints (`route`, `infer`, `train`, `benchmark`, `benchmark_compare`) funnel through. It is a
no-op when `project_context is None`, and otherwise wraps the actual write in its own
`try/except Exception: logger.exception(...)` — the same auxiliary-bookkeeping isolation pattern
Milestone 9 introduced for experiment/registry creation, applied here from the start rather than
discovered as a bug: a usage-recording failure must never affect the response the caller
already received.

`cost_estimate` is always `None` — there is no pricing model wired up yet (`Model.input_price` /
`output_price` have existed in the registry schema since Milestone 4, but nothing computes a cost
from them). The column is recorded now, always-`None` until a cost pass exists, matching how
`Experiment.cost_estimate` and `Experiment.model_version` were left in Milestone 8.

## What Gets Recorded Per Endpoint

| Endpoint | `router_name` | `model_name` | `tokens_input` / `tokens_output` |
|---|---|---|---|
| `POST /api/v1/route` | request router | result's resolved model | not tracked (no token metering exists) |
| `POST /api/v1/infer` | — | — | not tracked |
| `POST /api/v1/train` | request router | — | not tracked |
| `POST /api/v1/benchmark` | request router | — | `tokens_output = round(result.average_token_usage)` |
| `POST /api/v1/benchmark/compare` | — (multiple routers compared) | — | not tracked |

`average_token_usage` is a plain `float` that is never `None`, so `benchmark`'s `tokens_output` is
always populated (including a legitimate `0`, which is a real value, not "unknown").
`latency_ms` is measured around the actual work in every case (the job body for the three async
job endpoints, the request handler itself for `route`/`infer`).

## Endpoints

Both are read-only and project-scoped, gated by the same `require_project_role` dependency
Milestone 3 built — writing happens only as the side effect described above, never through these
routes.

| Method | Path | Auth |
|---|---|---|
| GET | `/projects/{project_id}/usage?limit=100` | Viewer+ of `project_id` |
| GET | `/projects/{project_id}/usage/summary` | Viewer+ of `project_id` |

`summary` runs a single aggregate query (`UsageRecordRepository.summary_for_project`) — count, sum
of tokens, average latency, sum of cost, and three `GROUP BY` breakdowns (by endpoint, by router,
by model) — rather than pulling every row into Python, so it scales with the database, not with
request volume.

## Testing

`tests/test_usage.py` — integration tests against the real dev Postgres container: a
project-scoped API key recording a `route` call, an unauthenticated `route` call recording nothing
(and not crashing — Phase 3 behavior preserved), `benchmark`'s token-estimate recording, summary
aggregation across two different routers/endpoints, RBAC 403 for a non-member, and an empty
project's summary returning zeros rather than nulls or errors.
