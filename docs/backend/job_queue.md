# Job Queue: Worker Processes, Leases, Retries

**Status:** replaces the in-process `BackgroundTasks` execution that Milestone 7 left in place.
`POST /train`, `/benchmark` and `/benchmark/compare` now only enqueue a row; separate worker
processes (`python -m backend.worker.main`) claim and run it. Postgres is the broker — no new
infrastructure.

## What changed, and why

Before: the API process created a `jobs` row, then ran the work itself via FastAPI
`BackgroundTasks`. If that process died mid-job the row stayed `running` forever; nothing
detected it, retried it, or let a second process help.

Now:

| Concern | Mechanism |
|---|---|
| Handing work over | Endpoints serialize the request + project-context ids into `jobs.payload` (JSONB) and return `202`. The worker rebuilds the job from the payload — no in-memory closure crosses the process boundary. |
| Atomic claim | `SELECT ... FOR UPDATE SKIP LOCKED` on the oldest eligible row (`queued`, or `running` with an expired lease). N workers can each take a different job in the same instant; none blocks another and none takes the same row. |
| Liveness | Claiming sets `jobs.leased_until = now + lease`. A heartbeat thread extends it while the job runs. |
| Crash recovery | A worker that dies without finishing stops renewing; once `leased_until` passes, any worker's claim query treats the row as eligible again and counts the reclaim against the retry budget. |
| Bounded retries | `retry_count` increments per failed attempt (an exception, or an expired-lease reclaim). Past `WORKER_MAX_RETRIES` (default 3) the job becomes terminal `dead_letter` instead of looping. |
| Idempotency | `register_router_version()` and `create_experiment()` check-then-create on the job id, and `training_job_details` (unique on `job_id`) is checked before insert, so a job executed twice leaves one version, one detail row, one experiment. |

State machine: `queued → running → completed`; failure → `queued` (retry) → … → `dead_letter`.
`cancelled` still exists in the enum but nothing sets it.

## Tunables (env vars)

`WORKER_LEASE_SECONDS` (120), `WORKER_HEARTBEAT_SECONDS` (30), `WORKER_POLL_INTERVAL_SECONDS` (1),
`WORKER_MAX_RETRIES` (3). The lease must comfortably exceed the heartbeat interval.

Run workers with Compose: `docker compose up -d --scale worker=N` (and set `WORKER_TORCH_THREADS` to about cores ÷ N). Workers never run migrations;
the `worker` service waits for the backend to be healthy first.

## What was verified (real runs, Docker Compose stack, fresh database, stock `llmrouter-lib`)

Workload: `knnrouter` benchmark jobs (5 queries each, about 1.4 s of CPU-bound work per job once
warm). One Docker host with 15 cores, so every worker shares the same CPUs.

- **Concurrent submission found a real bug.** Submitting 20 jobs at once with a project-scoped key
  returned HTTP 500 for 18 of them: `QueuePool limit of size 5 overflow 10 reached`. Each request
  held its request-scoped database connection while the job store opened a second one, so a burst
  used all 15 pooled connections with every request waiting for another. Fixed by releasing the
  request's connection before enqueueing (`_release_connection` in `management.py`) and by making the
  pool configurable (`DB_POOL_SIZE`/`DB_MAX_OVERFLOW`, defaults 10/20). Afterwards 30 concurrent
  submissions all returned 202. A regression test asserts the request holds no pooled connection when
  the job is created.
- **No double claims.** 30 jobs over 2 workers: all 30 completed, none failed, 30 distinct jobs
  claimed, **0 claimed more than once** (read from both workers' logs).
- **Kill test.** With a 20 s lease, `docker kill -s KILL` on a worker while it was mid-job. The job
  stayed `running` until the lease expired (~20 s), the surviving worker reclaimed it and it
  completed with `retry_count = 1`. Its claim appears once in each worker's log (the killed worker
  and the survivor), and the job completed once.
- **Throughput, 30 jobs per run, after a warm-up job per worker:**

  | Workers | PyTorch threads per worker | Elapsed | Throughput |
  |---|---|---|---|
  | 1 | unset (all cores) | 41.9 s | 42.9 jobs/min |
  | 2 | unset | 61.9 s | 29.1 jobs/min |
  | 4 | unset | 62.5 s | 28.8 jobs/min |
  | 1 | 15 | 42.1 s | 42.7 jobs/min |
  | 2 | 7 | 35.8 s | 50.3 jobs/min |
  | 4 | 3 | 33.9 s | 53.1 jobs/min |

  With PyTorch's default of one thread per core in every process, more workers made things
  **slower** (the processes oversubscribe the CPU). Capping threads per worker to about
  cores ÷ workers (`WORKER_TORCH_THREADS`) fixes that, but the gain is modest (about 1.2x at 4
  workers) because this job is short, CPU-bound and runs on one machine. These numbers show that the
  queue distributes work correctly and how to avoid oversubscription, not how it would scale across
  several hosts.

## Tests

`tests/test_worker_queue.py`: 8 threads racing for one job over 5 rounds (exactly one
winner each round); an expired lease being reclaimed and counted as a retry; repeated crashes
ending in `dead_letter`; explicit failures requeueing then dead-lettering; and running a train
job's work twice yielding one version / detail / experiment.

## Known limits

- A job is lost-and-retried, not resumed: a reclaimed training job restarts from scratch.
- One job at a time per worker process; concurrency comes from running more workers.
- No cancel endpoint; no per-job priority; retries have no backoff delay.
- Throughput was measured on one machine with one job type, with no network between services.
