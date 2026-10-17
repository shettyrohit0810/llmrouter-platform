"""OpenTelemetry tracing: one span per HTTP request (FastAPI), one span per
query (SQLAlchemy), and one span per command (redis-py), exported via
OTLP/HTTP if `OTEL_EXPORTER_OTLP_ENDPOINT` is set, else printed to stdout via
`ConsoleSpanExporter` -- so this milestone is observable with zero external
infrastructure. Point `OTEL_EXPORTER_OTLP_ENDPOINT` at a real collector
(Jaeger, Tempo, Grafana Alloy, etc.) to get an actual trace UI; see
docs/backend/observability.md.
"""

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)

from backend.config import BackendConfig
from backend.db.session import get_engine


def configure_tracing(app: FastAPI, config: BackendConfig) -> None:
    # set_tracer_provider() is a process-global, one-time operation by
    # design -- the OTel API logs a warning and keeps the existing provider
    # if called again, rather than raising, so repeated create_app() calls
    # in the same process (every test does this) are safe without extra
    # guarding here.
    resource = Resource.create({SERVICE_NAME: config.otel_service_name})
    provider = TracerProvider(resource=resource)
    if config.otel_exporter_otlp_endpoint:
        # Batches spans before a real network call to a collector -- where
        # batching actually earns its complexity.
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=config.otel_exporter_otlp_endpoint))
        )
    else:
        # SimpleSpanProcessor exports synchronously, inline, with no
        # background thread -- BatchSpanProcessor's worker thread would
        # otherwise keep trying to flush queued spans to stdout after a
        # test session (or process) has already torn down its output
        # streams, raising "I/O operation on closed file" during shutdown.
        # Printing to stdout per-span has no network cost to batch, so
        # there's no real tradeoff here.
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)

    # Per-app-instance (safe to call every create_app()).
    FastAPIInstrumentor.instrument_app(app)

    # Library-level monkeypatches. BaseInstrumentor is a singleton per
    # instrumentor class and tracks its own "already instrumented" state,
    # so a second call in the same process logs a warning and no-ops rather
    # than double-patching or raising.
    SQLAlchemyInstrumentor().instrument(engine=get_engine())
    RedisInstrumentor().instrument()
