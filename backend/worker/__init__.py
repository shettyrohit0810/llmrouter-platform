"""Real, out-of-process job queue worker.

Replaces the old approach (backend/api/routers/management.py's train/
benchmark/benchmark_compare handlers running work in-process via FastAPI's
BackgroundTasks, right after the HTTP response) with a standalone worker
process that polls the `jobs` table, claims work atomically with
`SELECT ... FOR UPDATE SKIP LOCKED`, and runs any number of these
concurrently -- each in its own process/container, sharing nothing but the
database. See docs/backend/job_queue.md.
"""
