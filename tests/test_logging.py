import json
import logging

from backend.api.middleware.logging_context import (
    JSONFormatter,
    RequestContextFilter,
    request_id_var,
)


def test_json_formatter_includes_request_id():
    logger = logging.getLogger("test.logging")
    logger.addFilter(RequestContextFilter())
    formatter = JSONFormatter()

    token = request_id_var.set("abc-123")
    try:
        record = logging.LogRecord(
            name="test.logging",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="hello",
            args=(),
            exc_info=None,
        )
        RequestContextFilter().filter(record)
        formatted = json.loads(formatter.format(record))
    finally:
        request_id_var.reset(token)

    assert formatted["request_id"] == "abc-123"
    assert formatted["message"] == "hello"
    assert formatted["level"] == "INFO"
