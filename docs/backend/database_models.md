# Database Models (Milestone 4)

**Status:** Phase 4, Milestone 4. Schema only — no service, repository, or endpoint code in this
milestone reads or writes any of the tables below. Each table is owned by a later milestone's
behavior layer, per `docs/design.md`'s Database Schema section:

| Table(s) | Behavior lands in |
|---|---|
| `jobs`, `training_job_details` | Milestone 7 (Persistent Job System) |
| `benchmark_results` | Milestone 7/8 |
| `experiments` | Milestone 8 (Experiment Tracking) |
| `routers`, `router_versions`, `models` | Milestone 9 (Model Registry) |
| `usage_records` | Milestone 10 (Usage Analytics) |
| `audit_logs` | Milestone 11 (Audit Logging) |

Migration `1ecfec987a4b` creates all nine (see its own docstring for rollback notes). `users`,
`organizations`, `organization_members`, `projects`, `api_keys`, `oauth_accounts`,
`refresh_tokens` already exist from Milestones 2–3.

## Why `JobRecord`, Not `Job`

Phase 3's `backend/api/services/jobs.py` already defines an in-memory `Job` dataclass. The new
ORM table's model class is named `JobRecord` specifically to stay unambiguous from that dataclass
until Milestone 7 reconciles the two (replacing `InMemoryJobStore` with a `PostgresJobStore`
backed by `JobRecord`, behind the same `JobStore` `Protocol` — no client-visible change, per
Phase 3's original design intent for that seam).

## Why `training_job_details` / `benchmark_results` Are Separate From `jobs`

`jobs` stays generic across every job type (train, benchmark, benchmark_compare) — it only knows
about lifecycle (status, timestamps, retry count), not what it's running. That mirrors Phase 3's
own `Job` dataclass contract. `training_job_details` and `benchmark_results` hold the
domain-specific fields (router name, config path, accuracy, routing distribution, ...) that don't
belong on the generic envelope, each a 1:1 detail row referencing `jobs.id`. `benchmark_results`'
columns are an exact mirror of `backend/api/schemas/benchmark.py`'s `BenchmarkResult` Pydantic
model — that schema's own docstring already called out being "designed so a future phase can
persist this to PostgreSQL without changing the API shape."

## The `metadata` Column Name Problem

Three tables (`RouterVersion`, `Experiment`, `AuditLog`) have a JSONB `metadata` column per the
ERD. `metadata` is reserved on SQLAlchemy's `DeclarativeBase` (it's the class attribute holding the
table's `MetaData` object) — naming a mapped Python attribute `metadata` shadows it and breaks the
ORM. Each model instead declares `metadata_: Mapped[dict | None] = mapped_column("metadata", ...)`
— the Python-side attribute is `metadata_`, the actual database column stays named `metadata`.
`tests/test_models.py::test_experiment_metadata_column_roundtrip` (and the equivalent
assertions in the Router/AuditLog tests) exist specifically to prove this rename round-trips
correctly through a real database, not just that the class imports without error.

## Nullable Foreign Keys (Transitional Pattern)

`jobs.project_id`, `jobs.created_by`, `router_versions.project_id` are all nullable, continuing
the same pattern `api_keys.project_id` established in Milestone 3: rows created by an
unauthenticated caller (Phase 3's original endpoints, still working unauthenticated per the
Migration Strategy) have no project or user to attach to. Enforcing `NOT NULL` on any of these is
a candidate for a later migration once the Phase 3 surface requires authentication.

## Testing

`tests/test_models.py` — integration tests against the real dev Postgres container for
every new model (`JobRecord`, `TrainingJobDetail`, `BenchmarkResult`, `Experiment`, `Router`,
`RouterVersion`, `Model`, `AuditLog`, `UsageRecord`), each doing a real create-then-refetch
round-trip rather than only asserting the class constructs. These can't run against in-memory
SQLite the way `tests/test_db.py`'s generic repository test does — `JSONB` and the
PostgreSQL-native `UUID` type are dialect-specific.
