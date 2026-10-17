# LLMRouter

A multi-tenant platform for training, serving and operating LLM routers: the accounts, access
control, quotas, job queue, tracking and audit layer you need to run routing as a product.

A router picks which language model should answer each query: cheap models for easy prompts,
strong ones for hard prompts. The routing algorithms themselves (KNN, Elo, MLP, SVM, and more) come
from the open-source [`llmrouter-lib`](https://pypi.org/project/llmrouter-lib/) package, used here as
an unmodified dependency. This repository is everything around them.

## What it provides

- **Accounts and tenancy.** Email/password and Google/GitHub sign-in, JWT access tokens with
  refresh-token rotation, organizations and projects, and project-scoped API keys.
- **Access control.** Owner / Admin / Developer / Viewer roles enforced per organization and
  project, including on jobs and audit logs.
- **Quotas.** Redis-backed rate limiting (sliding window per IP, token bucket per identity, plan
  tiers) using atomic Lua scripts.
- **Durable job queue.** Training and benchmark requests are queued in Postgres and run by
  separate worker processes: `SELECT ... FOR UPDATE SKIP LOCKED` claiming, heartbeat-renewed
  leases, automatic reclaim after a worker dies, bounded retries, and a dead-letter state.
  See [docs/backend/job_queue.md](docs/backend/job_queue.md).
- **Tracking.** Experiments, a versioned model registry, per-request usage analytics and an audit
  log of security-relevant actions.
- **Observability.** Prometheus metrics at `/metrics`; OpenTelemetry traces for requests, SQL and
  Redis, exported over OTLP.
- **Console.** A Next.js dashboard (`dashboard/`) for organizations, projects, usage, experiments,
  the registry, API keys, members and the audit log.
- **OpenAI-compatible gateway** mounted at `/v1`.

Architecture and data model: [docs/design.md](docs/design.md). Operations:
[docs/deployment.md](docs/deployment.md).

## Quick start

```bash
docker compose up -d --build --scale worker=2
```

- API and docs: http://localhost:8080/docs
- Dashboard: http://localhost:3000

```bash
B=http://localhost:8080/api/v1
curl -s -X POST $B/auth/register -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"a-long-password"}'
TOKEN=$(curl -s -X POST $B/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"a-long-password"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
AUTH="Authorization: Bearer $TOKEN"

ORG=$(curl -s -X POST $B/orgs -H "$AUTH" -H 'Content-Type: application/json' -d '{"name":"Acme"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')
PROJECT=$(curl -s -X POST $B/orgs/$ORG/projects -H "$AUTH" -H 'Content-Type: application/json' -d '{"name":"Prod"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')
KEY=$(curl -s -X POST $B/api-keys -H "$AUTH" -H 'Content-Type: application/json' -d "{\"name\":\"ci\",\"project_id\":\"$PROJECT\"}" | python3 -c 'import sys,json;print(json.load(sys.stdin)["api_key"])')

# Train a router: this returns a job id and a worker runs it. Poll
#   curl -s $B/jobs/<job_id> -H "X-API-Key: $KEY"
# until its status is "completed", then route a query with the trained router.
curl -s -X POST $B/train -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"router":"knnrouter","config_path":"configs/train/knnrouter.yaml"}'
curl -s -X POST $B/route -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"router":"knnrouter","config_path":"configs/serve/knnrouter.yaml","query":"What is 3 plus 9?"}'
```

Calls made with a project-scoped key are attributed to that project: they show up in its usage,
experiments and audit log.

The bundled configs train on a small synthetic dataset (`data/sample/`, regenerated with
`python scripts/generate_sample_data.py`) so everything runs without downloading anything.

## Development

```bash
python3.10 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
docker compose up -d postgres redis           # dev ports 5434 / 6380
alembic upgrade head
pytest                                         # integration tests use those containers
ruff check . && ruff format --check . && mypy backend

cd dashboard && npm install && npm run dev     # http://localhost:3000
```

## Layout

```
backend/      FastAPI app: routers, services, repositories, auth, RBAC, rate limiting,
              observability, and worker/ (the job queue worker)
dashboard/    Next.js console
configs/      Router training/serving configs and the gateway config
data/sample/  Synthetic sample dataset
scripts/      Sample-data generator
tests/        Integration and unit tests
docs/         Design, deployment and per-feature documentation
```

## Limits worth knowing

- A job reclaimed after a worker crash restarts from scratch; there is no checkpointed resume.
- Email verification and password-reset mail use a console stub; the OAuth `state` parameter is not
  verified. See [docs/deployment.md](docs/deployment.md#known-limits).
- Throughput and failure-recovery numbers in the job-queue doc come from one machine, not a
  multi-host deployment.
