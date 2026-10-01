"""Only one scoring run at a time across worker processes, and one log line per run (ADR-0003)."""

import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import select, text

from station_health.extensions import db
from station_health.health.models import FlagChangeRecord, ScoringRunRecord
from station_health.worker.__main__ import run_forever
from station_health.worker.scoring_run import SCORING_LOCK, ScoringRun, run_scoring_once
from tests.support import ADMIN_KEY, INGEST_KEY, START, OneCycle, auth, health_report, iso

RunWorker = Callable[[datetime], ScoringRun]


def submit_failing_station(client: FlaskClient) -> None:
    """Ten Health Reports with 3 errors each: a Hygiene Score of 40, so Poor Hygiene."""
    for minute in range(10):
        response = client.post(
            "/health-reports",
            json=health_report(timestamp=iso(START - timedelta(minutes=minute)), error_count=3),
            headers=auth(INGEST_KEY),
        )
        assert response.status_code == 201, response.json


@contextmanager
def lock_held_by_another_worker(app: Flask) -> Iterator[None]:
    with app.app_context(), db.engine.connect() as other_worker:
        held = other_worker.execute(text("SELECT GET_LOCK(:name, 0)"), {"name": SCORING_LOCK})
        assert held.scalar() == 1
        try:
            yield
        finally:
            # A pooled connection keeps its named locks, so release before handing it back.
            other_worker.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": SCORING_LOCK})


def flag_change_count(app: Flask) -> int:
    with app.app_context():
        return len(db.session.scalars(select(FlagChangeRecord.id)).all())


def test_a_scoring_run_skips_while_another_worker_holds_the_lock(
    app: Flask, client: FlaskClient
) -> None:
    submit_failing_station(client)

    with lock_held_by_another_worker(app), app.app_context():
        run = run_scoring_once(START)

        assert run is None
        assert db.session.scalars(select(ScoringRunRecord)).all() == []
    assert flag_change_count(app) == 0


def test_a_scoring_run_proceeds_once_the_other_worker_releases_the_lock(
    app: Flask, client: FlaskClient, run_worker: RunWorker
) -> None:
    submit_failing_station(client)
    with lock_held_by_another_worker(app), app.app_context():
        assert run_scoring_once(START) is None

    assert run_worker(START).flag_changes == 1
    # Each run releases the lock, so the next one is not skipped either.
    assert run_worker(START + timedelta(minutes=1)).scored_at == START + timedelta(minutes=1)


def test_concurrent_scoring_runs_at_the_same_now_record_each_flag_change_once(
    app: Flask, client: FlaskClient
) -> None:
    submit_failing_station(client)
    ready = threading.Barrier(4)
    runs: list[ScoringRun | None] = []

    def worker() -> None:
        with app.app_context():
            ready.wait()
            runs.append(run_scoring_once(START))

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(runs) == 4
    assert flag_change_count(app) == 1


def scoring_run_logs(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.getMessage().startswith("scoring run")]


def test_each_worker_cycle_logs_one_summary_line_for_its_scoring_run(
    app: Flask, client: FlaskClient, caplog: pytest.LogCaptureFixture
) -> None:
    submit_failing_station(client)
    response = client.put("/stations/ST-0002", json={"region": "eu-west"}, headers=auth(ADMIN_KEY))
    assert response.status_code == 201, response.json
    caplog.set_level(logging.INFO, logger="station_health.worker")

    run_forever(app, OneCycle())

    [line] = scoring_run_logs(caplog)
    assert line.getMessage() == "scoring run"
    assert vars(line)["stations_scored"] == 2
    # ST-0001 enters Poor Hygiene for errors, ST-0002 for being Silent.
    assert vars(line)["flag_changes"] == 2
    assert vars(line)["silent_stations"] == 1
    assert vars(line)["duration_ms"] >= 0


def test_a_skipped_scoring_run_logs_that_it_was_skipped(
    app: Flask, client: FlaskClient, caplog: pytest.LogCaptureFixture
) -> None:
    submit_failing_station(client)
    caplog.set_level(logging.INFO, logger="station_health.worker")

    with lock_held_by_another_worker(app):
        run_forever(app, OneCycle())

    [line] = scoring_run_logs(caplog)
    assert line.getMessage() == "scoring run skipped: another worker holds the lock"
