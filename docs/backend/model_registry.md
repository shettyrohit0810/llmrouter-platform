# Model Registry (Milestone 9)

**Status:** Phase 4, Milestone 9. Behavior layer on top of `routers`/`router_versions`/`models`
(Milestone 4, schema-only).

## Sync-on-Read, Not a Second Source of Truth

`Router` and `Model` rows are **upserted from the live in-code registries on every read** —
`GET /api/v1/registry/routers` calls `sync_and_list_routers()`, which reads
`backend/api/services/router_registry.py::list_routers()` (the existing thin wrapper over
`llmrouter.cli.router_inference.ROUTER_REGISTRY`, unchanged since Phase 3) and upserts by name into
the `routers` table. There are only ~20 routers, so re-syncing per request is cheap, and it means
the persisted table can never drift from what's actually installed — there is no separate "register
a router" write path, because a router isn't an event, it's a fact already known from code.
`RouterVersion`, in contrast, **is** an event (a specific trained checkpoint at a point in time) and
is created explicitly — either automatically when a training job completes, or manually via
`POST /api/v1/registry/router-versions`.

## Training Completion → Router Version → Experiment (Closing a Milestone 4 Gap)

`backend/api/routers/management.py`'s `train()` handler now does two additional things after
`train_router()` succeeds, each independently wrapped in `try/except` (see below):

1. **Reads the real checkpoint path** from the same YAML config already passed to
   `train_router()` — every router's training config declares `model_path.save_model_path`
   (verified across `configs/train/*.yaml`), so this is read directly rather than
   guessing a per-router naming convention (some routers, like `causallm_router`, save to a bare
   directory, not a `<name>.pkl` file).
2. **Registers a `RouterVersion`** (`version_label` auto-generated as `train-<8 hex chars>`,
   `checkpoint_path` from step 1, `training_job_id` set, `project_id` from the API-key's project
   context if any) and **creates the `TrainingJobDetail` row** linking `job_id` →
   `router_version_id` — closing a gap that had existed since Milestone 4: that table was defined
   in schema but nothing had ever written to it.
3. If Milestone 8's `create_experiment` flag is set, the resulting `Experiment.router_version`
   field is populated with the new `RouterVersion.id` — the two features are now connected: an
   experiment for a training run points at the specific version it produced.

## A Reliability Gap Found and Fixed (Applies Retroactively to Milestone 8 Too)

**Auxiliary bookkeeping (experiment/registry creation) was not isolated from the job's own
success/failure status.** `JobManager.run()` wraps the entire `_run` closure in one
`try/except` — if `_run` raised for *any* reason, the whole job was marked `FAILED`, even if the
actual training/benchmark work had already completed successfully and only the follow-up
bookkeeping (creating an `Experiment` row, now also registering a `RouterVersion`) failed. A
transient DB hiccup during experiment creation would have silently turned a **successful** training
run into a job the client sees as failed, with no indication that training itself was fine. Fixed
by wrapping each auxiliary block (`Experiment` creation, `RouterVersion` + `TrainingJobDetail`
creation) in its own `try/except Exception: logger.exception(...)` *inside* `_run`, so a failure in
either logs a server-side error but never affects `job.status` or `job.result` — applied to all
four endpoints' experiment-creation blocks (`train`, `benchmark`, `benchmark_compare`, `infer`),
not just the new registry-registration code that prompted noticing it.

## Endpoints

All require an authenticated user (`get_current_user`) — reading the router/model catalog is
shared platform metadata, not tenant-private data (the same way Phase 3's `/routers`/`/models`
were unauthenticated-readable). Writing a *project-scoped* version requires role membership,
checked inline (the project ID comes from the request body, not a path parameter
`require_project_role` can bind to):

| Method | Path | Auth |
|---|---|---|
| GET | `/registry/routers` | Any authenticated user |
| GET | `/registry/models` | Any authenticated user |
| POST | `/registry/router-versions` | Any user; Developer+ of `project_id` if one is given |
| GET | `/registry/router-versions?router_name=...` | Any authenticated user |
| GET | `/registry/router-versions/{id}` | Any authenticated user |
| POST | `/registry/router-versions/{id}/archive` | Any user; Admin+ of the version's project if it has one |

A version with no `project_id` (registered without one, or a legacy Milestone 2 API key) has no
natural owner in Phase 4's model — registering/archiving it requires only being logged in, the
same permissive-by-necessity scope RBAC already accepted for API keys without a project.

## Testing

`tests/test_registry.py` — integration tests against the real dev Postgres container:
sync-on-read for both routers and models, the full train → RouterVersion → TrainingJobDetail →
Experiment chain (verified with a real `elorouter` training run, checking the exact
`checkpoint_path` read from its YAML config), manual version registration with and without a
project, and RBAC enforcement (Developer+ to create a project-scoped version, Admin+ to archive
one).
