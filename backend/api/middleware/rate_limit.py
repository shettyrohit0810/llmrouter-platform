"""Rate-limiting middleware.

Unlike RBAC (Milestone 3), rate limiting needs only the request's client IP
and Authorization/X-API-Key headers -- no resolved path parameter -- so it
genuinely can be plain ASGI middleware, applied to every request before
routing, rather than a per-route dependency. This is the one place in Phase
4 where the spec's literal "middleware enforces X" holds without the
pragmatic reinterpretation RBAC needed.

Two checks per request:
1. IP-based sliding window (backend/ratelimit/plans.py's
   ANONYMOUS_IP_LIMIT) -- always applied, anti-abuse floor regardless of
   authentication.
2. Identity-based token bucket, sized from the caller's plan tier -- only
   applied when an API key or user was resolved (backend/ratelimit/
   identity.py); anonymous requests get IP-only limiting.

A 429 is written directly as a JSONResponse (not via HTTPException) because
middleware sits outside FastAPI's own exception-handling layer for
Starlette-level short-circuits -- constructing the response directly avoids
depending on exception-handler-middleware ordering.

Fails open on any Redis or database error: if the rate limiter's own
backing stores are unreachable (Redis directly for the limit checks,
Postgres indirectly via resolve_identity()'s API-key lookup), requests
proceed unthrottled rather than every request in the process turning into a
500. /health's own independent checks (backend/api/health/routes.py) are
what's supposed to surface an outage -- the rate limiter silently degrading
instead of crashing every request is what makes that check meaningful
rather than redundant with a flood of request-level failures.
"""

import logging
import time

import redis
import sqlalchemy.exc
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from backend.cache.client import get_redis
from backend.config import BackendConfig
from backend.ratelimit.algorithms import SlidingWindowLimiter, TokenBucketLimiter
from backend.ratelimit.identity import resolve_identity
from backend.ratelimit.plans import ANONYMOUS_IP_LIMIT, ANONYMOUS_IP_WINDOW_SECONDS, plan_limit

logger = logging.getLogger("backend.ratelimit")

_BACKING_STORE_ERRORS = (redis.RedisError, sqlalchemy.exc.SQLAlchemyError)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, config: BackendConfig):
        super().__init__(app)
        self._config = config
        self._sliding_window = SlidingWindowLimiter(get_redis())
        self._token_bucket = TokenBucketLimiter(get_redis())

    async def dispatch(self, request: Request, call_next):
        try:
            decision = self._check(request)
        except _BACKING_STORE_ERRORS:
            logger.warning("Rate limiter backing store unreachable -- failing open", exc_info=True)
            decision = None

        if decision is not None and not decision[0]:
            return self._too_many_requests(decision[1])

        response = await call_next(request)
        if decision is not None:
            response.headers["X-RateLimit-Remaining"] = str(int(decision[1]))
        return response

    def _check(self, request: Request):
        """Returns (allowed: bool, remaining_or_retry_after: float) or raises
        redis.RedisError -- kept separate from dispatch() so the whole
        identity-resolution + both-checks sequence is covered by one
        try/except, not just the final Redis call."""
        now = time.time()
        identity = resolve_identity(request, self._config)

        ip_result = self._sliding_window.check(
            f"ratelimit:ip:{identity.ip}", ANONYMOUS_IP_LIMIT, ANONYMOUS_IP_WINDOW_SECONDS, now
        )
        if not ip_result.allowed:
            return False, ip_result.retry_after_seconds

        if identity.kind == "anonymous":
            return True, ip_result.remaining

        limit = plan_limit(identity.plan)
        identity_result = self._token_bucket.check(
            f"ratelimit:{identity.kind}:{identity.identity_id}",
            limit.capacity,
            limit.refill_per_second,
            now,
        )
        if not identity_result.allowed:
            return False, identity_result.retry_after_seconds
        return True, identity_result.remaining

    @staticmethod
    def _too_many_requests(retry_after_seconds: float) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content={
                "error": "Rate limit exceeded",
                "error_type": "rate_limit_exceeded",
                "request_id": None,
            },
            headers={"Retry-After": str(max(1, int(retry_after_seconds)))},
        )
