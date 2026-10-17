# LLMRouter Platform — Design

A multi-tenant platform for training, serving and operating LLM routers. The routing algorithms
come from the published `llmrouter-lib` package; this repository adds everything needed to run
them as a product: accounts and tenancy, access control, quotas, a durable job queue, experiment
tracking, a model registry, usage analytics, audit logs and observability.

It is a **modular monolith**: one FastAPI application, one deployable (plus the worker processes
that run background jobs), PostgreSQL as the system of record and Redis for short-lived state.

## Architecture

```mermaid
graph TD
    Dash["Dashboard\n(separate deployable, REST-only client)"]
    Users["API clients / SDKs"]
    Dash -->|"HTTPS /api/v1/*"| App
    Users -->|"HTTPS /api/v1/*, /v1/*"| App

    subgraph App["FastAPI application (backend/)"]
        MW["Middleware: CORS, GZip, request logging,\nrate limiting, tracing/metrics"]
        Mgmt["Management API /api/v1/*\nauth, orgs, projects, routing, jobs,\nexperiments, registry, usage, audit"]
        Gateway["OpenAI-compatible gateway /v1/*\n(mounted from llmrouter-lib)"]
        RBAC["RBAC dependencies\nOwner / Admin / Developer / Viewer"]
        Repos["Repository layer (SQLAlchemy)"]
    end

    MW --> Mgmt
    MW --> Gateway
    Mgmt --> RBAC
    Mgmt --> Repos
    Mgmt --> Lib["llmrouter-lib\n(routing algorithms)"]
    Repos --> PG[("PostgreSQL\nusers, orgs, projects, jobs, experiments,\nregistry, audit, usage")]
    MW --> Redis[("Redis\nrate limits, cache")]
    Worker["Worker processes\npython -m backend.worker.main"] --> PG
    Worker --> Lib
```

Training and benchmark requests only enqueue a row in `jobs`; separate worker processes claim and
run them (see `docs/backend/job_queue.md`).

**Why PostgreSQL and Redis both.** Redis holds short-lived, high-write data that does not need
durability (rate-limit counters, caches). PostgreSQL holds everything that must survive a restart
and be queried relationally (users, orgs, jobs, experiments, audit trail).

**Router configs and paths.** Router YAML files reference data and checkpoints with relative
paths. The library resolves those against its own install directory, so
`backend/api/services/config_resolver.py` rewrites them to absolute paths under the platform root
(`PLATFORM_ROOT`, default: the project directory) before handing the config to the library.

**Conventions.** Every schema change is an Alembic migration with a tested `downgrade()`. Database
access goes through repository classes. Auxiliary bookkeeping (experiments, usage, audit) is
isolated so a failure there never fails the request or job that triggered it. Existing
unauthenticated routing endpoints stay usable; sending a project-scoped API key additionally
attributes the call to a project for tracking, usage and rate limiting.

## Database Schema

All tables use a UUID primary key (`id`) unless noted. All tables get `created_at`; tables that
are mutated after creation also get `updated_at`. Managed entirely through Alembic migrations
(the initial migration creates the first tables; every later change to a table adds
its own migration — no hand-edited schema).

```mermaid
erDiagram
    USERS ||--o{ OAUTH_ACCOUNTS : has
    USERS ||--o{ REFRESH_TOKENS : has
    USERS ||--o{ ORGANIZATION_MEMBERS : "member of"
    ORGANIZATIONS ||--o{ ORGANIZATION_MEMBERS : has
    ORGANIZATIONS ||--o{ PROJECTS : has
    PROJECTS ||--o{ API_KEYS : has
    PROJECTS ||--o{ JOBS : has
    PROJECTS ||--o{ EXPERIMENTS : has
    PROJECTS ||--o{ ROUTER_VERSIONS : has
    JOBS ||--o| TRAINING_JOB_DETAILS : "1:1 when job_type=train"
    JOBS ||--o| BENCHMARK_RESULTS : "1:1 when job_type=benchmark"
    JOBS ||--o{ EXPERIMENTS : "0:1 originates"
    ROUTERS ||--o{ ROUTER_VERSIONS : has
    ROUTER_VERSIONS ||--o| JOBS : "trained by"
    ORGANIZATIONS ||--o{ AUDIT_LOGS : has
    ORGANIZATIONS ||--o{ USAGE_RECORDS : has

    USERS {
        uuid id PK
        string email UK
        string hashed_password "nullable, OAuth-only users have none"
        string full_name
        bool is_active
        bool is_email_verified
        timestamp last_login_at
        timestamp created_at
    }
    OAUTH_ACCOUNTS {
        uuid id PK
        uuid user_id FK
        string provider "google | github"
        string provider_account_id
        timestamp created_at
    }
    REFRESH_TOKENS {
        uuid id PK
        uuid user_id FK
        string token_hash "hash only, never raw"
        timestamp expires_at
        bool revoked
        timestamp created_at
    }
    ORGANIZATIONS {
        uuid id PK
        string name
        string slug UK
        string plan "free | developer | enterprise"
        timestamp created_at
    }
    ORGANIZATION_MEMBERS {
        uuid id PK
        uuid organization_id FK
        uuid user_id FK
        string role "owner | admin | developer | viewer"
        timestamp created_at
    }
    PROJECTS {
        uuid id PK
        uuid organization_id FK
        string name
        string slug
        timestamp created_at
    }
    API_KEYS {
        uuid id PK
        uuid project_id FK
        string name
        string key_prefix "shown in UI, e.g. lr_live_ab12"
        string key_hash "sha256 of full key, never stored plaintext"
        uuid created_by FK
        timestamp last_used_at
        timestamp expires_at "nullable"
        bool revoked
        timestamp created_at
    }
    JOBS {
        uuid id PK
        uuid project_id FK
        string job_type "train | benchmark | benchmark_compare"
        string status "queued|running|completed|failed|cancelled"
        int progress "nullable, 0-100"
        jsonb result
        text error
        jsonb logs "append-only log lines"
        int retry_count
        uuid created_by FK "nullable"
        timestamp created_at
        timestamp started_at
        timestamp completed_at
    }
    TRAINING_JOB_DETAILS {
        uuid id PK
        uuid job_id FK
        string router_name
        string config_path
        string device
        string router_version_id FK "nullable, filled on completion"
    }
    BENCHMARK_RESULTS {
        uuid id PK
        uuid job_id FK
        string router
        string dataset
        int num_queries
        float accuracy
        float average_latency_seconds
        float average_token_usage
        jsonb routing_distribution
        int failures
        text evaluation_summary
    }
    EXPERIMENTS {
        uuid id PK
        uuid project_id FK
        uuid job_id FK "nullable"
        string experiment_type "train|benchmark|benchmark_compare|infer"
        string router_name
        string router_version
        string model_version
        jsonb metrics
        jsonb metadata
        float cost_estimate
        float duration_seconds
        uuid created_by FK
        timestamp created_at
    }
    ROUTERS {
        uuid id PK
        string name UK
        string class_name
        bool trainable
        string status "active | deprecated | unsupported"
        jsonb tags
        timestamp created_at
    }
    ROUTER_VERSIONS {
        uuid id PK
        uuid router_id FK
        uuid project_id FK "nullable, org-shared if null"
        string version_label
        string checkpoint_path
        uuid training_job_id FK "nullable"
        jsonb metadata
        string status "active | archived"
        timestamp created_at
    }
    MODELS {
        uuid id PK
        string name UK
        string provider
        text description
        int context_limit
        float input_price
        float output_price
        jsonb tags
        timestamp created_at
    }
    AUDIT_LOGS {
        uuid id PK
        uuid organization_id FK "nullable"
        uuid project_id FK "nullable"
        uuid user_id FK "nullable"
        uuid api_key_id FK "nullable"
        string action "e.g. auth.login, job.train.start, apikey.create"
        string resource_type
        string resource_id
        jsonb metadata
        string ip_address
        timestamp created_at
    }
    USAGE_RECORDS {
        uuid id PK
        uuid organization_id FK
        uuid project_id FK
        uuid api_key_id FK "nullable"
        uuid user_id FK "nullable"
        string endpoint
        string router_name "nullable"
        string model_name "nullable"
        float latency_ms
        int tokens_input "nullable"
        int tokens_output "nullable"
        float cost_estimate "nullable"
        int status_code
        timestamp created_at
    }
```

**Why `jobs` stays generic and `training_job_details`/`benchmark_results` are separate tables.**
The existing `Job` dataclass (the original) is already generic across `train`/`benchmark`/
`benchmark_compare` — it doesn't know what it's running, only its lifecycle. Keeping that
contract at the database level (one `jobs` table, one `JobStore` implementation) means
`JobManager` still doesn't need to know about routers or benchmarks. `training_job_details` and
`benchmark_results` hold the domain-specific fields the platform needs to query/aggregate that
don't belong on the generic envelope — mirroring the same separation of concerns as
`backend/api/services/benchmark.py` (orchestration) vs. `backend/api/services/jobs.py` (generic
execution) in the original.


## Authentication Model

Two independent client types authenticate differently, both terminating in the same
`get_current_principal` FastAPI dependency used by every protected route:

1. **Human users (dashboard, interactive API use)** — email+password or OAuth (Google/GitHub),
   issued a short-lived **JWT access token** (≈15 min) and a longer-lived **refresh token**
   (≈30 days, stored hashed in `refresh_tokens`, rotated on use). Access tokens are stateless
   (verified by signature, not a DB lookup) so they impose no per-request DB cost; refresh tokens
   are checked against the DB specifically so they can be revoked (logout, password reset,
   suspected compromise).
2. **Programmatic/API clients** — an **API key** (`lr_live_<random>` format), scoped to exactly
   one project. The full key is shown once at creation time and never stored — only
   `sha256(key)` and a short `key_prefix` (for display/identification) are persisted. Every
   request presenting an API key looks up by hash, checks `revoked`/`expires_at`, and updates
   `last_used_at`.

**Password hashing:** `passlib`'s `bcrypt` scheme (industry-standard, self-salting, adjustable
work factor) — never a custom hash.

**OAuth (Google, GitHub):** standard authorization-code flow. On callback, the backend exchanges
the code for the provider's profile (email, provider account ID), links or creates a `User` +
`OAuthAccount` row, and issues the same JWT/refresh-token pair as password login — OAuth users are
otherwise indistinguishable from password users to the rest of the system.

**Password reset:** time-limited, single-use signed token (same JWT-signing infrastructure, short
TTL, a dedicated `purpose: password_reset` claim so a leaked reset token can't be replayed as a
login token) emailed to the user.

**Email verification:** **stub only** in this platform, per the approved spec — the interface
(`EmailSender` protocol + a `ConsoleEmailSender` implementation that logs instead of sending) is
built so a real provider (SES, Postmark, etc.) can be swapped in later without changing the
verification flow's calling code.

**Session management:** "session" here means the refresh-token lifecycle above, not
server-side session state — no server-side session store is needed beyond the `refresh_tokens`
table, keeping the backend itself stateless between requests (any instance can validate any
access token).

## User Model

A `User` is a person, not scoped to any organization by itself — a `User` becomes a member of one
or more `Organization`s via `OrganizationMember` rows, each carrying its own `role`. This lets one
person belong to multiple organizations with different roles in each (e.g. Owner of their own org,
Viewer on a client's), which is standard SaaS multi-tenancy shape and matches "Organizations,
Users" being listed as separate top-level entities in the spec rather than users nesting inside
one organization.

## Organization Model

`Organization` is the billing/plan boundary (`plan: free | developer | enterprise`, consumed by
the rate-limit plan tiers). `Project` is the operational boundary underneath it — API
keys, jobs, experiments, and router versions all belong to a `Project`, not directly to an
`Organization`, so a single organization can isolate different workloads (e.g. "staging" vs
"production" projects) with separate API keys and separate job/experiment history while still
rolling up to one plan and one set of members for billing and access control.

