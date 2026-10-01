"""The simulator's backfill: `flask backfill-reports` bulk-loads past Health Reports through
ingest's validation and storage, and the worker's summary catch-up turns them into trend.
"""

from datetime import timedelta
from typing import Any

from click.testing import Result
from flask import Flask
from flask.testing import FlaskClient

from station_health.simulator.profiles import Profile, fleet
from station_health.worker.__main__ import run_forever
from tests.support import ADMIN_KEY, READ_KEY, START, FakeClock, OneCycle, auth, iso

HOUR = timedelta(hours=1)


def backfill(app: Flask, *args: str) -> Result:
    return app.test_cli_runner().invoke(args=["backfill-reports", *args])


def run_one_worker_cycle(app: Flask) -> None:
    run_forever(app, OneCycle())


def trend(client: FlaskClient, hours: int) -> Any:
    response = client.get("/metrics/trend", query_string={"hours": hours}, headers=auth(READ_KEY))
    assert response.status_code == 200, response.json
    return response.json


def station_of(profile: Profile) -> str:
    return next(s.station_id for s in fleet(10) if s.profile is profile)


def test_after_one_worker_run_the_trend_has_data_for_every_backfilled_hour(
    app: Flask, client: FlaskClient, clock: FakeClock
) -> None:
    result = backfill(app, "--stations", "10", "--hours", "3")
    assert result.exit_code == 0, result.output

    # Hours are summarised 5 minutes after they end.
    clock.now = START + timedelta(minutes=5)
    run_one_worker_cycle(app)

    points = trend(client, hours=4)["points"]
    assert [p["hour"] for p in points] == [iso(START - h * HOUR) for h in (4, 3, 2, 1)]
    # Before the backfill: nothing.
    assert points[0]["reporting_station_count"] == 0
    # The goes-Silent Station reports only in the first backfilled minutes.
    assert [p["reporting_station_count"] for p in points[1:]] == [10, 9, 9]
    # Flapping, slow and error-prone Stations average below the Flag Threshold.
    assert all(p["below_flag_threshold_count"] >= 3 for p in points[1:])
    assert all(p["average_hygiene_score"] is not None for p in points[1:])


def test_backfill_reports_what_it_stored_and_ignores_duplicates_when_run_again(
    app: Flask, client: FlaskClient, run_worker: Any
) -> None:
    first = backfill(app, "--stations", "10", "--hours", "1")
    again = backfill(app, "--stations", "10", "--hours", "1")

    assert first.exit_code == 0, first.output
    assert again.exit_code == 0, again.output
    # One Health Report per minute from an hour ago up to and including now, except the
    # goes-Silent Station, which stops after 10 simulated minutes.
    assert "Stored 559 Health Reports, 0 duplicates ignored" in first.output
    assert "Stored 0 Health Reports, 559 duplicates ignored" in again.output

    run_worker(START)
    response = client.get(f"/stations/{station_of(Profile.HEALTHY)}/health", headers=auth(READ_KEY))
    assert response.json["hygiene"]["report_count"] == 15


def test_backfill_registers_the_fleet_like_the_live_simulator(
    app: Flask, client: FlaskClient
) -> None:
    backfill(app, "--stations", "10", "--hours", "1")

    registered = client.get(f"/stations/{station_of(Profile.HEALTHY)}", headers=auth(ADMIN_KEY))
    assert registered.json["verified"] is True
    assert registered.json["region"] == "us-west"
    unregistered = client.get(
        f"/stations/{station_of(Profile.UNREGISTERED)}", headers=auth(ADMIN_KEY)
    )
    assert unregistered.status_code == 200
    assert unregistered.json["verified"] is False
    assert unregistered.json["region"] is None


def test_backfill_can_fill_all_of_raw_retention_and_every_report_passes_validation(
    app: Flask, clock: FakeClock
) -> None:
    # Off a whole minute, so the oldest whole minute in reach is just inside retention.
    clock.now = START + timedelta(seconds=30)

    result = backfill(app, "--stations", "1", "--hours", "48")

    assert result.exit_code == 0, result.output
    assert "Stored 2880 Health Reports, 0 duplicates ignored" in result.output


def test_backfill_hours_cannot_exceed_raw_retention(app: Flask) -> None:
    result = backfill(app, "--hours", "49")

    assert result.exit_code != 0
    assert "raw retention" in result.output
