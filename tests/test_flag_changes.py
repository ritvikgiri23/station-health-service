"""Poor Hygiene, Silent and Flag Changes across successive scoring runs."""

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import select

from station_health.extensions import db
from station_health.health.models import FlagChangeRecord
from station_health.worker.scoring_run import ScoringRun
from tests.support import INGEST_KEY, READ_KEY, START, FakeClock, auth, health_report, iso

RunWorker = Callable[[datetime], ScoringRun]


def submit(client: FlaskClient, at: datetime, **fields: Any) -> None:
    response = client.post(
        "/health-reports", json=health_report(timestamp=iso(at), **fields), headers=auth(INGEST_KEY)
    )
    assert response.status_code == 201, response.json


def submit_minutely(client: FlaskClient, start: datetime, count: int, **fields: Any) -> None:
    """`count` Health Reports a minute apart, the last at `start`."""
    for minute in range(count):
        submit(client, start - timedelta(minutes=minute), **fields)


def hygiene(client: FlaskClient, station_id: str = "ST-0001") -> Any:
    response = client.get(f"/stations/{station_id}/health", headers=auth(READ_KEY))
    assert response.status_code == 200, response.json
    return response.json["hygiene"]


def flag_changes(app: Flask) -> list[tuple[str, datetime, str, str, int | None]]:
    """The Flag Change log, oldest first."""
    with app.app_context():
        records = db.session.scalars(select(FlagChangeRecord).order_by(FlagChangeRecord.id))
        return [
            (r.station_id, r.changed_at, r.direction, r.flag_reason, r.hygiene_score)
            for r in records
        ]


def test_a_station_scoring_below_the_flag_threshold_enters_poor_hygiene(
    app: Flask, client: FlaskClient, run_worker: RunWorker
) -> None:
    # 3 errors per Health Report: error score 0, Hygiene Score 40.
    submit_minutely(client, START, 10, error_count=3)

    run = run_worker(START)

    body = hygiene(client)
    assert body["score"] == 40
    assert body["silent"] is False
    assert body["poor_hygiene"] is True
    assert body["flag_reason"] == "errors"
    assert body["flagged_since"] == iso(START)
    assert run.flag_changes == 1
    assert flag_changes(app) == [("ST-0001", START, "entered", "errors", 40)]


def test_a_healthy_station_is_not_flagged(client: FlaskClient, run_worker: RunWorker) -> None:
    submit_minutely(client, START, 10)

    run = run_worker(START)

    body = hygiene(client)
    assert body["poor_hygiene"] is False
    assert body["flag_reason"] is None
    assert body["flagged_since"] is None
    assert run.flag_changes == 0


def test_a_station_goes_silent_and_must_earn_clearing(
    app: Flask, client: FlaskClient, clock: FakeClock, run_worker: RunWorker
) -> None:
    submit_minutely(client, START, 10)
    run_worker(START)

    # No Health Reports for 20 minutes: nothing is left in the 15-minute Scoring Window.
    silent_at = clock.now = START + timedelta(minutes=20)
    run_worker(silent_at)
    assert hygiene(client) == {
        "score": None,
        "availability": None,
        "latency_score": None,
        "error_score": None,
        "p95_latency_ms": None,
        "report_count": 0,
        "silent": True,
        "poor_hygiene": True,
        "flag_reason": "silent",
        "flagged_since": iso(silent_at),
    }

    # One good Health Report ends Silent, but is not enough evidence to clear.
    clock.now = silent_at + timedelta(minutes=1)
    submit(client, clock.now)
    run_worker(clock.now)
    body = hygiene(client)
    assert body["score"] == 100
    assert body["silent"] is False
    assert body["poor_hygiene"] is True
    assert body["flagged_since"] == iso(silent_at)

    # Five good Health Reports in the window clear it.
    recovered_at = clock.now = silent_at + timedelta(minutes=5)
    submit_minutely(client, recovered_at, 4)
    run_worker(recovered_at)
    body = hygiene(client)
    assert body["poor_hygiene"] is False
    assert body["flag_reason"] is None
    assert body["flagged_since"] is None

    assert flag_changes(app) == [
        ("ST-0001", silent_at, "entered", "silent", None),
        # Leaving records the Flag Reason it last had: once reporting, its lowest part.
        ("ST-0001", recovered_at, "left", "availability", 100),
    ]


def test_a_station_hovering_between_the_thresholds_does_not_flicker(
    app: Flask, client: FlaskClient, clock: FakeClock, run_worker: RunWorker
) -> None:
    # 2 errors per Health Report scores 60 (at the Flag Threshold); 3 per report scores 40.
    submit_minutely(client, START, 15, error_count=3)
    run_worker(START)
    # Each run's window then holds only reports scoring 60: still below the Clear Threshold.
    for step in range(1, 4):
        now = clock.now = START + timedelta(minutes=15 * step)
        submit_minutely(client, now, 15, error_count=2)
        run_worker(now)
        assert hygiene(client)["score"] == 60
        assert hygiene(client)["poor_hygiene"] is True

    assert [change[2] for change in flag_changes(app)] == ["entered"]


def test_only_stations_whose_visible_state_changed_are_written(
    client: FlaskClient, run_worker: RunWorker
) -> None:
    submit(client, START - timedelta(minutes=2), station_id="ST-STEADY")
    submit(client, START - timedelta(minutes=2), station_id="ST-FAILING")
    first = run_worker(START)
    assert first.stations_written == 2

    submit(client, START, station_id="ST-STEADY")
    submit(client, START, station_id="ST-FAILING", connectivity_status="offline")
    second = run_worker(START + timedelta(minutes=1))

    # ST-STEADY still scores 100; only ST-FAILING's score changed.
    assert second.stations_scored == 2
    assert second.stations_written == 1
    assert hygiene(client, "ST-FAILING")["score"] == 50


def test_flag_changes_of_several_stations_are_recorded_in_order(
    app: Flask, client: FlaskClient, clock: FakeClock, run_worker: RunWorker
) -> None:
    submit_minutely(client, START, 5, station_id="ST-A", connectivity_status="offline")
    submit_minutely(client, START, 5, station_id="ST-B")
    run_worker(START)
    later = clock.now = START + timedelta(minutes=20)
    submit_minutely(client, later, 5, station_id="ST-A")
    run_worker(later)

    assert flag_changes(app) == [
        ("ST-A", START, "entered", "availability", 0),
        ("ST-A", later, "left", "availability", 100),
        ("ST-B", later, "entered", "silent", None),
    ]
