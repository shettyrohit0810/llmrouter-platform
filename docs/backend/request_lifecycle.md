# Backend Request Lifecycle

Companion to `docs/backend/architecture.md`. Three sequences: a synchronous management request,
an asynchronous background job, and the error path. All three pass through the same middleware
stack described there (CORS → GZip → request logging/timing → handler → exception handlers).

## 1. Synchronous Request (e.g. `POST /api/v1/route`)

```mermaid
sequenceDiagram
    participant C as Client
    participant CORS as CORSMiddleware
    participant Log as RequestLoggingMiddleware
    participant H as management.route()
    participant L as llmrouter.cli.router_inference

    C->>CORS: POST /api/v1/route {router, config_path, query}
    CORS->>Log: forward
    Log->>Log: request_id = uuid4(), stored in request_id_var
    Log->>H: forward
    H->>L: load_router(router, config_path)
    L-->>H: router_instance
    H->>L: route_query(query, router_instance, router)
    L-->>H: {model_name, routing_result, ...}
    H-->>Log: 200 RouteResponse
    Log->>Log: elapsed = time.time() - start
    Log-->>C: 200 + X-Request-ID + X-Execution-Time headers
```

The handler never touches middleware or job machinery directly — it is exactly the two existing
library calls (`load_router`, `route_query`) wrapped in a Pydantic request/response pair.

## 2. Background Job (e.g. `POST /api/v1/train`)

```mermaid
sequenceDiagram
    participant C as Client
    participant H as management.train()
    participant JM as JobManager
    participant JS as JobStore (in-memory)
    participant BG as FastAPI BackgroundTasks
    participant L as llmrouter.cli.router_train

    C->>H: POST /api/v1/train {router, config_path, device}
    H->>JM: submit("train", fn)
    JM->>JS: create(Job(status=queued))
    JS-->>JM: job
    JM-->>H: job
    H->>BG: add_task(JM.run, job.job_id, fn)
    H-->>C: 202 {job_id, status: "queued"}

    Note over BG,L: Runs after the response has already been sent
    BG->>JM: run(job_id, fn)
    JM->>JS: update(job_id, status=running, started_at=now)
    JM->>L: fn() -> train_router(router, config_path, device)
    L-->>JM: result dict
    JM->>JS: update(job_id, status=completed, result=..., completed_at=now)

    C->>H: GET /api/v1/jobs/{job_id}
    H->>JS: get(job_id)
    JS-->>H: Job(status=completed, result=...)
    H-->>C: 200 JobResponse
```

The client receives `202` before `train_router` ever runs — polling `GET /api/v1/jobs/{job_id}`
is the only way to observe completion. `benchmark` and `benchmark/compare` follow the identical
shape, substituting `run_benchmark`/`run_benchmark_compare` for `train_router`.

## 3. Error Path (any endpoint, sync or inside a job)

```mermaid
sequenceDiagram
    participant C as Client
    participant H as Handler (sync) or JobManager.run (background)
    participant EH as Exception Handlers
    participant Log as Server-side logger

    alt Synchronous request
        C->>H: request
        H->>H: raises HTTPException / ValidationError / Exception
        H->>EH: FastAPI dispatches to matching handler
        EH->>Log: (unhandled Exception only) logger.error(..., exc_info=True)
        EH-->>C: {error, error_type, request_id} + status code
    else Background job
        C->>H: POST (already returned 202)
        H->>H: fn() raises inside JobManager.run
        H->>Log: JobManager._log_traceback(exc) — full traceback, server-side only
        H->>H: job.status = failed, job.error = str(exc)
        C->>H: GET /api/v1/jobs/{job_id}
        H-->>C: {status: "failed", error: str(exc)}
    end
```

Both paths share one invariant, verified by
`tests/test_error_handling.py::test_unhandled_exception_never_leaks_traceback`: a client
never receives a traceback or file path, only a short string. The full exception detail exists
exactly once — in the server-side log — correlated to the failing request/job via the same
`request_id` (synchronous path) or `job_id` (background path).
