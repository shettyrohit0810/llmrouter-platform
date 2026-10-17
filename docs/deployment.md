# Deployment

## Components

| Service | Image / command | Port | Notes |
|---|---|---|---|
| `backend` | `uvicorn backend.app:app` | 8080 | API + OpenAI-compatible gateway. Runs `alembic upgrade head` on start. |
| `worker` | `python -m backend.worker.main` | — | Runs training/benchmark jobs. Scale with `--scale worker=N`. Never migrates. |
| `dashboard` | Next.js (standalone) | 3000 | Static client of `/api/v1/*`; holds no secrets. |
| `postgres` | `postgres:16-alpine` | 5434 (dev) | System of record. |
| `redis` | `redis:7-alpine` | 6380 (dev) | Rate-limit state. |

```bash
docker compose up -d --build --scale worker=2
# API:        http://localhost:8080   (OpenAPI docs at /docs)
# Dashboard:  http://localhost:3000
# Metrics:    http://localhost:8080/metrics
```

Backend and workers share the `llmrouter_saved_models` volume: workers write trained checkpoints,
the API loads them for inference. On more than one host, replace it with shared storage.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | local dev Postgres | SQLAlchemy URL. |
| `REDIS_URL` | local dev Redis | Rate limiting. |
| `JWT_SECRET_KEY` | **insecure dev value** | **Must be set** in any shared environment. There is no runtime check. |
| `ACCESS_TOKEN_TTL_MINUTES` / `REFRESH_TOKEN_TTL_DAYS` | 15 / 30 | Token lifetimes. |
| `GOOGLE_OAUTH_*`, `GITHUB_OAUTH_*` | unset | Client id/secret/redirect URI; a provider is disabled (501) without them. |
| `CORS_ALLOW_ORIGINS` | `*` | Comma-separated browser origins. Set to the dashboard origin. |
| `PLATFORM_ROOT` | project directory | Base for relative router config / data / checkpoint paths. |
| `BACKEND_GATEWAY_CONFIG` | `configs/gateway.yaml` | Config for the mounted `/v1` gateway. |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` / `DB_POOL_TIMEOUT` | 10 / 20 / 30 | SQLAlchemy pool, per process. |
| `WORKER_LEASE_SECONDS` / `WORKER_HEARTBEAT_SECONDS` | 120 / 30 | Job lease and its renewal interval. |
| `WORKER_POLL_INTERVAL_SECONDS` / `WORKER_MAX_RETRIES` | 1 / 3 | Idle poll interval; failures before dead-letter. |
| `WORKER_TORCH_THREADS` | unset | PyTorch threads per worker. Unset, every worker uses all cores and several workers on one machine slow each other down; set it to about `cores / workers`. |
| `OTEL_SERVICE_NAME` / `OTEL_EXPORTER_OTLP_ENDPOINT` | `llmrouter-backend` / unset | Unset prints spans to stdout; set to export OTLP/HTTP to a collector. |
| `PUBLIC_API_URL` | `http://localhost:8080` | Compose build arg: the API address the **browser** calls, inlined into the dashboard bundle. |

Size the database for `(backend replicas × (DB_POOL_SIZE + DB_MAX_OVERFLOW)) + (workers × 2)`
connections.

## Production checklist

- Set `JWT_SECRET_KEY` to a long random value, and `CORS_ALLOW_ORIGINS` to the dashboard origin.
- Terminate TLS in front of the API and dashboard; the API does not serve HTTPS itself.
- Run migrations once per deploy (`alembic upgrade head`) rather than from every replica's start
  command if you run more than one backend replica.
- Back up Postgres. Job state, experiments, registry and audit logs all live there.
- Scrape `/metrics` (Prometheus) and point `OTEL_EXPORTER_OTLP_ENDPOINT` at a collector.
- Email verification and password-reset mail go through a console stub
  (`backend/api/auth/email.py`); wire in a real sender before relying on them.

## Known limits

- The OAuth `state` parameter is generated but not verified server-side.
- A reclaimed (crashed-worker) job restarts from scratch; there is no checkpointed resume.
- Rate limiting fails open if Redis is unreachable; `/health` reports the outage.
- The dashboard keeps tokens in `localStorage`, so it is exposed to any XSS in the page.
