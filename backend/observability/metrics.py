"""Prometheus metrics. `http_requests_total`/`http_request_duration_seconds`
are recorded by RequestLoggingMiddleware (Phase 3, Milestone 5) -- reusing
the timing it already computes rather than adding a second timing pass --
and `job_submissions_total` by JobManager.submit() (Phase 3, Milestone 2),
the single chokepoint every async job (train/benchmark/benchmark_compare)
already goes through. `/metrics` is unauthenticated and unversioned (not
under /api/v1), matching the standard Prometheus scrape convention and
/health's own existing unversioned placement.
"""

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests handled",
    ["method", "path", "status_code"],
)
http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path"],
)
job_submissions_total = Counter(
    "job_submissions_total",
    "Total async jobs submitted",
    ["job_type"],
)

router = APIRouter()


@router.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
