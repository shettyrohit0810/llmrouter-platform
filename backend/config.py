"""Backend application configuration."""

import os
from dataclasses import dataclass


@dataclass
class BackendConfig:
    host: str = "0.0.0.0"
    port: int = 8080
    log_level: str = "info"
    # Config for the OpenAI-compatible gateway app (from the llmrouter-lib
    # package) that this backend mounts under /v1.
    gateway_config_path: str = "configs/gateway.yaml"
    # Project root: relative router config / data / checkpoint paths are
    # resolved against this (see backend/api/services/config_resolver.py).
    # Override with PLATFORM_ROOT, e.g. to point at a mounted volume.
    repo_root: str = os.environ.get(
        "PLATFORM_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )

    # PostgreSQL connection string (SQLAlchemy URL). Defaults to the local dev
    # container started for Phase 4 (see docs/backend/database.md).
    database_url: str = (
        "postgresql+psycopg2://llmrouter:llmrouter_dev_password@localhost:5434/llmrouter"
    )

    # JWT signing. The default is dev-only and MUST be overridden via
    # JWT_SECRET_KEY in any shared/production environment -- there is no
    # runtime check enforcing this (Phase 4 does not add a secrets-management
    # system; see docs/deployment for that discussion), so it is a documented
    # operational responsibility, not an automatic guardrail.
    jwt_secret_key: str = "dev-only-insecure-secret-do-not-use-in-production"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30

    # OAuth (Google/GitHub). None disables that provider's endpoints returning
    # a clear 501, the same "feature absent without config" pattern Phase 3
    # used for LLM provider API keys.
    google_oauth_client_id: str | None = None
    google_oauth_client_secret: str | None = None
    google_oauth_redirect_uri: str | None = None
    github_oauth_client_id: str | None = None
    github_oauth_client_secret: str | None = None
    github_oauth_redirect_uri: str | None = None

    # Redis connection string. Defaults to the local dev container started
    # for Milestone 5 (see docs/backend/caching.md).
    redis_url: str = "redis://localhost:6380/0"

    # OpenTelemetry. otel_exporter_otlp_endpoint=None (the default) means
    # traces print to stdout via ConsoleSpanExporter -- no external collector
    # required to see this milestone work. Setting it to a real collector's
    # URL (e.g. a local Jaeger/Tempo/Grafana Alloy instance) switches to
    # OTLP/HTTP export instead; see docs/backend/observability.md.
    otel_service_name: str = "llmrouter-backend"
    otel_exporter_otlp_endpoint: str | None = None

    # Browser origins allowed to call the API (CORS). "*" suits local
    # development; set CORS_ALLOW_ORIGINS to the dashboard's origin(s),
    # comma-separated, in any shared deployment.
    cors_allow_origins: tuple[str, ...] = ("*",)

    @classmethod
    def from_env(cls) -> "BackendConfig":
        return cls(
            host=os.environ.get("BACKEND_HOST", "0.0.0.0"),
            port=int(os.environ.get("BACKEND_PORT", "8080")),
            log_level=os.environ.get("BACKEND_LOG_LEVEL", "info"),
            gateway_config_path=os.environ.get("BACKEND_GATEWAY_CONFIG", "configs/gateway.yaml"),
            database_url=os.environ.get(
                "DATABASE_URL",
                "postgresql+psycopg2://llmrouter:llmrouter_dev_password@localhost:5434/llmrouter",
            ),
            jwt_secret_key=os.environ.get(
                "JWT_SECRET_KEY", "dev-only-insecure-secret-do-not-use-in-production"
            ),
            jwt_algorithm=os.environ.get("JWT_ALGORITHM", "HS256"),
            access_token_ttl_minutes=int(os.environ.get("ACCESS_TOKEN_TTL_MINUTES", "15")),
            refresh_token_ttl_days=int(os.environ.get("REFRESH_TOKEN_TTL_DAYS", "30")),
            google_oauth_client_id=os.environ.get("GOOGLE_OAUTH_CLIENT_ID"),
            google_oauth_client_secret=os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET"),
            google_oauth_redirect_uri=os.environ.get("GOOGLE_OAUTH_REDIRECT_URI"),
            github_oauth_client_id=os.environ.get("GITHUB_OAUTH_CLIENT_ID"),
            github_oauth_client_secret=os.environ.get("GITHUB_OAUTH_CLIENT_SECRET"),
            github_oauth_redirect_uri=os.environ.get("GITHUB_OAUTH_REDIRECT_URI"),
            redis_url=os.environ.get("REDIS_URL", "redis://localhost:6380/0"),
            otel_service_name=os.environ.get("OTEL_SERVICE_NAME", "llmrouter-backend"),
            otel_exporter_otlp_endpoint=os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"),
            cors_allow_origins=tuple(
                o.strip() for o in os.environ.get("CORS_ALLOW_ORIGINS", "*").split(",") if o.strip()
            )
            or ("*",),
        )
