"""Gunicorn settings. Gunicorn's own logs use the same JSON format as the app's."""

import os

bind = "0.0.0.0:8000"
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
accesslog = None  # the app logs one JSON line per request itself
log_level = os.environ.get("LOG_LEVEL", "INFO").upper()

logconfig_dict = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"json": {"()": "station_health.log.JsonFormatter"}},
    "handlers": {
        "stdout": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "stream": "ext://sys.stdout",
        }
    },
    # The app factory attaches its own JSON handler to the root logger.
    "root": {"level": log_level, "handlers": []},
    "loggers": {
        "gunicorn.error": {"handlers": ["stdout"], "level": log_level, "propagate": False},
    },
}
