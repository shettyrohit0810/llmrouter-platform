"""Structured logging: one JSON line per log record, with request ID,
execution time, router/model selected, and errors/warnings threaded through
via contextvars so nested calls (e.g. inside a background job) still log
with the originating request ID when available."""

import contextvars
import json
import logging
import time

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": time.time(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging(log_level: str = "info") -> None:
    root = logging.getLogger()
    root.setLevel(log_level.upper())
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    handler.addFilter(RequestContextFilter())
    root.handlers = [handler]
