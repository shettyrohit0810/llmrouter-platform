# Experiment Tracking (Milestone 8)

**Status:** Phase 4, Milestone 8. Behavior layer on top of the `experiments` table (Milestone 4,
schema-only). Implements exactly the design `docs/design.md` committed to in
Phase 4's API Changes section.

## Opt-In, Project-Scoped

Every `/api/v1/train`, `/api/v1/benchmark`, `/api/v1/benchmark/compare`, and `/api/v1/infer`
request gains a `create_experiment: bool` field (default `True` for the first three, `False` for
`infer` — inference is comparatively high-volume/low-value to record individually). Setting it to
`True` only actually creates a record if the request also resolves a **project context** — and
that only happens for API-key-authenticated calls whose key has a `project_id`
(`backend/api/dependencies/project_context.py::get_optional_project_context`). A bare JWT user or
an anonymous call gets no experiment, regardless of the flag — there's no unambiguous project to
attach to (the identical limitation Milestone 6's rate-limit plan resolution hit; a user can belong
to several organizations/projects, and Phase 3's original endpoints aren't project-scoped).

This mirrors `docs/design.md`'s Migration Strategy exactly: existing endpoints
gain an *optional* authenticated identity that scopes new persistence when present, and behave
exactly as they did in Phase 3 when absent.

## Where Creation Happens

- **`/train`, `/benchmark`, `/benchmark/compare`** are async (job-based) — the experiment is
  created *inside* the background job's `_run` closure, after the real result is known (so
  `metrics`/`duration_seconds` reflect the actual run), using its own `session_scope()` (the
  closure executes via `BackgroundTasks`, after the request's own DI-provided session has already
  closed — same pattern Milestone 7's `PostgresJobStore` uses).
- **`/infer`** is synchronous — the experiment is created inline, in the same request, using the
  request's own `Depends(get_db)` session.

`GET /api/v1/jobs/{id}` and `GET /api/v1/jobs` now populate an optional `experiment_id` field by
looking up `Experiment.job_id == job_id` — not a new required field, so no existing client parsing
`JobResponse` breaks. `InferResponse` gained the same field directly (inference has no job to look
one up from).

## What's Recorded, What Isn't Yet

| Field | Populated? |
|---|---|
| `experiment_type`, `router_name`, `duration_seconds`, `created_by` | Yes |
| `metrics` (accuracy/latency/token-usage for benchmark; ranking for compare; success for infer) | Yes |
| `metadata` (dataset/sample_size/device/temperature — whatever's request-specific) | Yes |
| `router_version` | Populated for `train` as of Milestone 9 (the newly registered `RouterVersion.id`); `None` for other experiment types |
| `model_version`, `cost_estimate` | **Always `None`** |

**Update (Milestone 9):** `train`'s experiment now carries `router_version` — the ID of the
`RouterVersion` row Milestone 9's registry created for that same training job (see
`docs/backend/model_registry.md`). `model_version`/`cost_estimate` stay `None` — there is still no
model-version-tagging system or cost model wired up. Recording the columns now, always-`None`
until those exist, avoids another migration later — the same "add the column before the feature
that fills it" pattern Milestone 4 already used for `training_job_details.router_version_id`.

## Reading Experiments

- `GET /api/v1/projects/{project_id}/experiments` — list, requires Viewer+ membership
  (`require_project_role`, same RBAC dependency Milestone 3 built).
- `GET /api/v1/experiments/{experiment_id}` — single record, requires membership in the owning
  project's organization (looked up via the experiment's `project_id`).

## A Real Bug Found During Verification

**`resolve_identity()`'s API-key branch raised `DetachedInstanceError` on every single
API-key-authenticated request.** `backend/ratelimit/identity.py` (Milestone 6) fetched the
`APIKey` row inside a `with session_scope() as db:` block, but checked `key_row.revoked` and
returned `key_row.id` *after* that block had already exited and closed the session — an ORM
attribute access on a detached instance raises `sqlalchemy.orm.exc.DetachedInstanceError` rather
than returning the (already-fetched) value. This went undetected through all of Milestone 6
because:

1. No existing rate-limit test exercised the API-key branch of `resolve_identity()` end-to-end
   (only the JWT and anonymous branches were tested).
2. The rate-limit middleware's own fail-open behavior (also Milestone 6) caught the exception and
   silently treated every API-key request as if the rate limiter were down, logging a warning and
   letting the request through unthrottled — exactly the intended behavior for a genuine Redis/DB
   outage, but here it was masking a real code bug in the identity-resolution logic itself, not an
   actual infrastructure failure.

Milestone 8 is what first exercised a real end-to-end API-key-authenticated request against the
full middleware stack (to attach an experiment to a project), surfacing it. Fixed by moving the
`revoked`/`id` reads inside the `with` block. Regression test:
`tests/test_ratelimit.py::test_resolve_identity_valid_api_key_does_not_raise`.

## A Test-Runtime Bug Found During Verification

The first version of this milestone's `benchmark_compare` test omitted `sample_size`, so
`run_benchmark_compare()` evaluated the *entire* default dataset (hundreds of queries) for two
routers with real `route_single()` calls per query — no caching, no cap. The test ran for over an
hour, consuming 500%+ CPU continuously, before being killed. The test's actual objective was
"does this create an Experiment record with the right shape," not "benchmark real accuracy," so
the fix was to cap every benchmark/benchmark_compare call in `tests/test_experiments.py` with
`"sample_size": 5` — when dataset size interferes with the test objective, shrink the input
rather than letting the test run for hours. Full file now runs in under 30 seconds.

## Testing

`tests/test_experiments.py` — integration tests against the real dev Postgres container:
experiment creation (and non-creation, when the flag is `False` or no project context resolves)
for all four endpoint types, `experiment_id` propagation into `JobResponse`/`InferResponse`, RBAC
enforcement on both read endpoints (403 for non-members, 404 for unknown IDs), and list ordering.
Every test that needs a project-scoped API key assigns `project_id` on the key row directly at the
DB layer, since no endpoint currently accepts one at creation time (API keys are created
project-agnostic in Milestones 2/3) — documented in the test file's own module docstring as a
stand-in for a future "create a project-scoped key" endpoint.
