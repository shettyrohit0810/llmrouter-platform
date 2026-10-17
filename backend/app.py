"""Unified backend ASGI application.

Hosts two API surfaces under one deployable:
- /api/v1/*  -- new management API (this package)
- /v1/*      -- OpenAI-compatible gateway, provided by the llmrouter-lib package

The gateway app is mounted as a sub-application rather than reimplemented, so
the platform adds auth/tenancy/quotas around it without forking its code.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from backend.config import BackendConfig
from backend.api.exceptions.handlers import register_exception_handlers
from backend.api.health.routes import router as health_router
from backend.api.middleware.logging_context import configure_logging
from backend.api.middleware.rate_limit import RateLimitMiddleware
from backend.api.middleware.request_logging import RequestLoggingMiddleware
from backend.api.routers.api_keys import router as api_keys_router
from backend.api.routers.audit import router as audit_router
from backend.api.routers.auth import router as auth_router
from backend.api.routers.experiments import router as experiments_router
from backend.api.routers.management import router as management_router
from backend.api.routers.organizations import router as organizations_router
from backend.api.routers.registry import router as registry_router
from backend.api.routers.usage import router as usage_router
from backend.cache.client import init_redis
from backend.db.session import init_engine
from backend.observability.metrics import router as metrics_router
from backend.observability.tracing import configure_tracing


@asynccontextmanager
async def _lifespan(app: FastAPI):
    logging.getLogger("backend.lifecycle").info("Backend starting up")
    yield
    logging.getLogger("backend.lifecycle").info("Backend shutting down")


def create_app(config: BackendConfig | None = None) -> FastAPI:
    config = config or BackendConfig.from_env()
    configure_logging(config.log_level)
    init_engine(config.database_url)
    init_redis(config.redis_url)

    app = FastAPI(
        title="LLMRouter Backend",
        description="Production backend: management API + mounted OpenAI-compatible API",
        version="0.1.0",
        lifespan=_lifespan,
    )
    register_exception_handlers(app)
    # After init_engine()/init_redis() (needs a live Engine to instrument)
    # and before any middleware/routes are added, so every request and
    # query is traced from the start.
    configure_tracing(app, config)

    # Middleware order: Starlette applies middleware in reverse of the order
    # added (last added = outermost). RequestLoggingMiddleware is added first
    # so it runs innermost, giving it the most accurate per-request timing.
    # RateLimitMiddleware sits inside CORS (added before it) so a browser's
    # OPTIONS preflight is handled by CORS and never consumes rate-limit
    # quota; CORS is added last so it wraps everything (needed for preflight
    # requests to be handled before any other processing).
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(RateLimitMiddleware, config=config)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(config.cors_allow_origins),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register this backend's own routes FIRST -- Starlette checks routes in the
    # order they were added, so /health here wins over the gateway's own
    # /health once mounted below at the same exact path.
    app.include_router(health_router)
    # Unversioned, unauthenticated, root-level -- standard Prometheus scrape
    # convention, matching /health's own placement.
    app.include_router(metrics_router)

    # Versioned management API.
    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(management_router)
    api_v1.include_router(auth_router)
    api_v1.include_router(api_keys_router)
    api_v1.include_router(organizations_router)
    api_v1.include_router(experiments_router)
    api_v1.include_router(registry_router)
    api_v1.include_router(usage_router)
    api_v1.include_router(audit_router)
    app.include_router(api_v1)

    # Mount the gateway app at root. Its own routes (/v1/models,
    # /v1/chat/completions, /v1/chat/ws) stay reachable at their usual paths.
    from openclaw_router import create_app as create_gateway_app

    gateway_app = create_gateway_app(config_path=config.gateway_config_path)
    app.mount("", gateway_app)

    return app


app = create_app()
