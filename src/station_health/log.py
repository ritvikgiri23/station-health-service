"""Structured JSON logging, with a request ID attached to every request."""

import json
import logging
import re
import sys
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from flask import Flask, Response, g, has_request_context, request

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")
_HANDLER_NAME = "station_health_json"

# Attributes every LogRecord has; anything else was passed via `extra=` and is logged as a field.
_STANDARD_ATTRS = frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if has_request_context() and "request_id" in g:
            entry["request_id"] = g.request_id
        for key, value in vars(record).items():
            if key not in _STANDARD_ATTRS:
                entry[key] = value
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def configure_logging(level: str) -> None:
    """Send all logs to stdout as JSON lines. Safe to call more than once."""
    root = logging.getLogger()
    for existing in [h for h in root.handlers if h.get_name() == _HANDLER_NAME]:
        root.removeHandler(existing)
    handler = logging.StreamHandler(sys.stdout)
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level)


def init_request_logging(app: Flask) -> None:
    """Tag each request with an ID (the caller's, or a new one) and log one line per request."""
    logger = logging.getLogger("station_health.request")

    @app.before_request
    def assign_request_id() -> None:
        supplied = request.headers.get(REQUEST_ID_HEADER, "")
        g.request_id = supplied if _VALID_REQUEST_ID.fullmatch(supplied) else uuid.uuid4().hex
        g.request_started = time.perf_counter()

    @app.after_request
    def log_request(response: Response) -> Response:
        response.headers[REQUEST_ID_HEADER] = g.request_id
        logger.info(
            "request",
            extra={
                "method": request.method,
                "path": request.path,
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - g.request_started) * 1000, 1),
            },
        )
        return response
