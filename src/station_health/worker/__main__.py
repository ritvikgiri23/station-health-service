"""The worker process: `python -m station_health.worker`.

A thin loop: every WORKER_INTERVAL_SECONDS (start to start), until SIGTERM or SIGINT,
a scoring run, then hourly summary catch-up, then retention clean-up. Catch-up runs
before retention so an hour is summarised before its Health Reports can expire. Each
step fails on its own, so a failing clean-up never stops scoring. Each step logs one
line with its result, so the scoring run's line carries Stations scored, Flag Changes,
the Silent count and duration.
"""

import logging
import signal
import threading
import time
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime
from typing import Any

from flask import Flask

from station_health.app import create_app
from station_health.runtime import current_settings, current_time
from station_health.worker.retention import run_retention
from station_health.worker.scoring_run import run_scoring_once
from station_health.worker.summary_catch_up import run_summary_catch_up

logger = logging.getLogger("station_health.worker")


def main() -> None:
    app = create_app()
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    run_forever(app, stop)


def run_forever(app: Flask, stop: threading.Event) -> None:
    with app.app_context():
        interval = current_settings().worker_interval.total_seconds()
    logger.info("worker started", extra={"interval_seconds": interval})
    while not stop.is_set():
        started = time.monotonic()
        _step(app, "scoring run", run_scoring_once)
        _step(app, "summary catch-up", run_summary_catch_up)
        _step(app, "retention", run_retention)
        stop.wait(max(0.0, interval - (time.monotonic() - started)))
    logger.info("worker stopped")


def _step(app: Flask, name: str, step: Callable[[datetime], Any]) -> None:
    """Run one worker step as of now and log its result's fields.

    A step returns None when it skipped: only a scoring run does, when another worker
    holds its lock.
    """
    try:
        with app.app_context():
            result = step(current_time())
        if result is None:
            logger.info(f"{name} skipped: another worker holds the lock")
        else:
            logger.info(name, extra=asdict(result))
    except Exception:
        # A failed step (e.g. the database restarting) must not stop the worker.
        logger.exception(f"{name} failed")


if __name__ == "__main__":
    main()
