"""Request-logging + timing middleware: assigns a request ID, times the
request, logs router/model selected when present in the response body, and
records Prometheus request metrics (Milestone 12) -- reusing this
middleware's own timing rather than adding a second timing pass."""

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from backend.api.middleware.logging_context import request_id_var
from backend.observability.metrics import http_request_duration_seconds, http_requests_total

logger = logging.getLogger("backend.requests")


def _route_path(request: Request) -> str:
    # The route's path *template* (e.g. "/projects/{project_id}/usage"), not
    # request.url.path -- using the raw path would give every distinct
    # project_id its own Prometheus time series (unbounded cardinality).
    # Falls back to the raw path for unmatched routes (404s), where there's
    # no template and cardinality is naturally bounded by "paths someone
    # actually requested".
    route = request.scope.get("route")
    return route.path if route is not None else request.url.path


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        token = request_id_var.set(request_id)
        request.state.request_id = request_id
        start = time.time()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        elapsed = time.time() - start
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Execution-Time"] = f"{elapsed:.4f}"
        path = _route_path(request)
        http_requests_total.labels(
            method=request.method, path=path, status_code=str(response.status_code)
        ).inc()
        http_request_duration_seconds.labels(method=request.method, path=path).observe(elapsed)
        logger.info(
            "%s %s -> %s (%.4fs) [request_id=%s]",
            request.method,
            request.url.path,
            response.status_code,
            elapsed,
            request_id,
        )
        return response
