# Persistent Job System (Milestone 7)

**Status:** Phase 4, Milestone 7. Replaces Phase 3's `InMemoryJobStore` as the default job store with
`PostgresJobStore`, backed by the `jobs` table (`backend/db/models/jobs.py::JobRecord`) added
schema-only in Milestone 4. This is the seam Phase 3's `JobStore` `Protocol` was explicitly
designed for (`docs/backend/architecture.md`: "a real backing store could replace
`InMemoryJobStore` without changing any client-visible API").

## What Changed, What Didn't

- `get_job_manager()` now constructs `JobManager(PostgresJobStore())` instead of
  `JobManager(InMemoryJobStore())`. That is the *only* line that changed in
  `backend/api/routers/management.py`'s call path — no endpoint, no request/response schema,
  no `Job`/`JobResponse` field changed.
- `InMemoryJobStore` is untouched and still exported — kept for fast unit tests that don't need a
  real database (`tests/test_jobs.py`), per the migration doc's stated plan.
- `JobRecord` has four columns (`project_id`, `created_by`, `logs`, `retry_count`) that
  `PostgresJobStore` does not populate yet: no endpoint has an authenticated project context to
  attach a job to (Phase 3's `/train`, `/benchmark`, `/benchmark/compare` remain unauthenticated —
  see the Migration Strategy), and Phase 4 adds no automatic retry policy. These stay at their
  column defaults (`NULL`/`NULL`/`NULL`/`0`) until a later phase has a caller for them.

## Design

`PostgresJobStore` implements the same four methods as `InMemoryJobStore`
(`create`/`get`/`update`/`list`), translating between the `Job` dataclass (unchanged, in-process
shape `JobManager` and the API schemas use) and `JobRecord` rows:

- Timestamps: `Job`'s are `float` (epoch seconds, matching `time.time()`); `JobRecord`'s are
  timezone-aware `datetime`. Converted both ways (`_to_epoch`/`_to_datetime`).
- Each method opens its own session via `session_scope()` rather than taking a `Session`
  parameter — `JobStore`'s `Protocol` doesn't thread one through, and `JobManager.run()` executes
  via FastAPI `BackgroundTasks` after the request that submitted the job (and its
  DI-provided session) has already completed.

## A Bug Found During Verification

**A malformed `job_id` crashed with a 500 instead of a 404.** `GET /api/v1/jobs/does-not-exist`
   worked fine against `InMemoryJobStore`'s plain dict lookup (any string is a valid key), but
   `PostgresJobStore.get()` called `uuid.UUID(job_id)` directly — an invalid UUID string raises
   `ValueError`, which bubbled up as a generic 500 rather than the client's actual mistake (a
   bad/nonexistent ID) producing a clean 404. Caught by
   `tests/test_error_handling.py::test_404_returns_uniform_error_shape`, which predates
   this milestone and started failing once the store swap landed. Fixed with a
   `_parse_job_id()` helper that treats an unparseable ID the same as "not found" (`None`) in both
   `get()` and `update()`, rather than letting the exception escape — regression test in
   `tests/test_job_persistence.py::
   test_postgres_job_store_get_malformed_id_returns_none_not_raises`. The rest of the swap was a
   mechanical, well-typed translation layer with no other surprises.

## Testing

`tests/test_job_persistence.py` — integration tests against the real dev Postgres
container: the full lifecycle (create → run → fetch, success and failure paths), `list()`
ordering, the malformed-ID regression above, and — the actual point of this milestone —
**`test_job_survives_across_independent_store_instances`**: a job created through one
`PostgresJobStore` instance is fetched through a completely separate instance, proving state lives
in Postgres and not in any Python object. Verified once more directly against the real REST API and
Docker container (see the Milestone 7 completion notes in the commit): a real `POST /api/v1/train`
job for `elorouter` was submitted, then the in-process `JobManager` singleton was discarded
entirely (simulating a restart) and `GET /api/v1/jobs/{id}` still returned the correct
`status: "completed"` and result.
