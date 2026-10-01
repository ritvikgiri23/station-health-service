"""The worker process: `python -m station_health.worker`.

A thin loop around `run_scoring_once`: one scoring run every WORKER_INTERVAL_SECONDS
(start to start), until SIGTERM or SIGINT.
"""

import logging
import signal
import threading
import time

from flask import Flask

from station_health.app import create_app
from station_health.runtime import current_settings, current_time
from station_health.worker.scoring_run import run_scoring_once

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
        try:
            with app.app_context():
                run = run_scoring_once(current_time())
            logger.info(
                "scoring run",
                extra={
                    "stations_scored": run.stations_scored,
                    "stations_written": run.stations_written,
                    "flag_changes": run.flag_changes,
                    "duration_ms": run.duration_ms,
                },
            )
        except Exception:
            # A failed run (e.g. the database restarting) must not stop the worker.
            logger.exception("scoring run failed")
        stop.wait(max(0.0, interval - (time.monotonic() - started)))
    logger.info("worker stopped")


if __name__ == "__main__":
    main()
