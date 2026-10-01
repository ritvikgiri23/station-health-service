"""The worker's hourly summary catch-up and retention clean-up."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import insert, select

from station_health.extensions import db
from station_health.health.models import SCORING_RUN_RECORD_ID, ScoringRunRecord
from station_health.reports.models import HealthReport
from station_health.summaries.models import HourlySummary
from station_health.worker.__main__ import run_forever
from station_health.worker.retention import Retention, run_retention
from station_health.worker.summary_catch_up import SummaryCatchUp, run_summary_catch_up
from tests.support import INGEST_KEY, FakeClock, OneCycle, auth, health_report, iso

H9 = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
HOUR = timedelta(hours=1)


def submit(client: FlaskClient, clock: FakeClock, received: datetime, **fields: Any) -> None:
    """Submit a Health Report with the clock at `received`."""
    clock.now = received
    response = client.post(
        "/health-reports", json=health_report(**fields), headers=auth(INGEST_KEY)
    )
    assert response.status_code == 201, response.json


def submit_hour(
    client: FlaskClient,
    clock: FakeClock,
    received: datetime,
    station_id: str,
    hour_start: datetime,
    online: bool = True,
) -> None:
    """Twelve Health Reports, one every 5 minutes through the hour."""
    for minute in range(0, 60, 5):
        submit(
            client,
            clock,
            received,
            station_id=station_id,
            timestamp=iso(hour_start + timedelta(minutes=minute)),
            connectivity_status="online" if online else "offline",
            latency_ms=100 if online else 5000,
        )


def catch_up(app: Flask, now: datetime) -> SummaryCatchUp:
    with app.app_context():
        return run_summary_catch_up(now)


def summaries(app: Flask) -> list[tuple[datetime, str]]:
    with app.app_context():
        rows = db.session.execute(
            select(HourlySummary.hour_start, HourlySummary.station_id).order_by(
                HourlySummary.hour_start, HourlySummary.station_id
            )
        )
        return [(hour_start, station_id) for hour_start, station_id in rows]


def summary(app: Flask, hour_start: datetime, station_id: str) -> HourlySummary:
    with app.app_context():
        row = db.session.get(HourlySummary, (hour_start, station_id))
        assert row is not None
        db.session.expunge(row)
        return row


def test_catch_up_summarises_every_completed_hour_missed_during_a_worker_outage(
    app: Flask, client: FlaskClient, clock: FakeClock
) -> None:
    submit_hour(client, clock, H9 + HOUR, "ST-A", H9)
    in_progress = H9 + HOUR + timedelta(minutes=2)
    submit(
        client, clock, in_progress, station_id="ST-A", timestamp=iso(in_progress), latency_ms=100
    )

    # 09:00 is summarised five minutes after it ends, giving its last Health Reports time
    # to arrive; 10:00 is still in progress.
    assert catch_up(app, H9 + HOUR + timedelta(minutes=4)) == SummaryCatchUp(0, 0)
    assert catch_up(app, H9 + HOUR + timedelta(minutes=5)) == SummaryCatchUp(1, 1)
    assert summaries(app) == [(H9, "ST-A")]

    # The worker is down until 13:30, while Health Reports keep arriving.
    resumed = H9 + 4 * HOUR + timedelta(minutes=30)
    for hour in (H9 + HOUR, H9 + 2 * HOUR, H9 + 3 * HOUR):
        submit_hour(client, clock, resumed, "ST-A", hour)
        submit_hour(client, clock, resumed, "ST-B", hour, online=hour != H9 + 2 * HOUR)
    submit(client, clock, resumed, station_id="ST-A", timestamp=iso(H9 + 4 * HOUR))

    assert catch_up(app, resumed) == SummaryCatchUp(3, 6)
    assert summaries(app) == [
        (H9, "ST-A"),
        *(
            (hour, station)
            for hour in (H9 + HOUR, H9 + 2 * HOUR, H9 + 3 * HOUR)
            for station in ("ST-A", "ST-B")
        ),
    ]
    healthy = summary(app, H9 + HOUR, "ST-A")
    # Twelve from during the outage, and the 10:02 one from before it.
    assert healthy.report_count == 13
    assert healthy.online_count == 13
    assert healthy.average_latency_ms == 100
    assert healthy.max_latency_ms == 100
    assert healthy.p95_latency_ms == 100
    assert healthy.error_count_sum == 0
    assert healthy.average_hygiene_score == 100
    offline = summary(app, H9 + 2 * HOUR, "ST-B")
    assert (offline.report_count, offline.online_count) == (12, 0)
    assert offline.average_latency_ms is None
    assert offline.average_hygiene_score == 0


def test_running_catch_up_twice_writes_no_duplicate_summaries(
    app: Flask, client: FlaskClient, clock: FakeClock
) -> None:
    now = H9 + 3 * HOUR
    submit_hour(client, clock, now, "ST-A", H9)
    submit_hour(client, clock, now, "ST-A", H9 + HOUR)

    assert catch_up(app, now) == SummaryCatchUp(2, 2)
    assert catch_up(app, now) == SummaryCatchUp(0, 0)
    assert summaries(app) == [(H9, "ST-A"), (H9 + HOUR, "ST-A")]


def test_catch_up_skips_an_hour_partly_past_raw_retention(
    app: Flask, client: FlaskClient, clock: FakeClock
) -> None:
    now = H9 + timedelta(days=2, minutes=30)
    # 09:00 two days ago starts before now - 48h, so retention may have taken some of it.
    submit(client, clock, now, station_id="ST-A", timestamp=iso(H9 + timedelta(minutes=40)))
    submit(client, clock, now, station_id="ST-A", timestamp=iso(H9 + HOUR + timedelta(minutes=10)))

    assert catch_up(app, now) == SummaryCatchUp(1, 1)
    assert summaries(app) == [(H9 + HOUR, "ST-A")]


RunRetention = Callable[[datetime], Retention]


@pytest.fixture
def retention(make_client: Callable[..., FlaskClient]) -> RunRetention:
    """Retention clean-up with batches of 2 rows, so it takes several."""
    app = make_client(RETENTION_BATCH_SIZE="2").application

    def run(now: datetime) -> Retention:
        with app.app_context():
            return run_retention(now)

    return run


def test_retention_deletes_raw_health_reports_older_than_raw_retention(
    app: Flask, client: FlaskClient, clock: FakeClock, retention: RunRetention
) -> None:
    received = H9 + timedelta(days=2)
    expired = [H9 + timedelta(minutes=m) for m in (0, 1, 2)]
    boundary = H9 + timedelta(minutes=3)
    recent = received - timedelta(minutes=5)
    for timestamp in [*expired, boundary, recent]:
        submit(client, clock, received, timestamp=iso(timestamp))

    # 48 hours after `boundary`: it is exactly at the retention limit, so it stays.
    assert retention(boundary + timedelta(hours=48)) == Retention(3, 0)

    with app.app_context():
        assert list(db.session.scalars(select(HealthReport.timestamp))) == [boundary, recent]


def test_retention_deletes_hourly_summaries_older_than_summary_retention(
    app: Flask, retention: RunRetention
) -> None:
    now = H9 + timedelta(days=40, minutes=30)
    # Whole hours: the hour starting 30 days before this one is kept.
    limit = H9 + timedelta(days=10)
    hours = [limit - 3 * HOUR, limit - 2 * HOUR, limit - HOUR, limit, now - HOUR]
    with app.app_context():
        db.session.execute(
            insert(HourlySummary),
            [
                {
                    "hour_start": hour,
                    "station_id": "ST-A",
                    "report_count": 1,
                    "online_count": 1,
                    "average_latency_ms": 100,
                    "max_latency_ms": 100,
                    "p95_latency_ms": 100,
                    "error_count_sum": 0,
                    "average_hygiene_score": 100,
                }
                for hour in hours
            ],
        )
        db.session.commit()

    assert retention(now) == Retention(0, 3)
    assert summaries(app) == [(limit, "ST-A"), (now - HOUR, "ST-A")]


def test_each_worker_cycle_scores_then_catches_up_summaries_then_applies_retention(
    app: Flask, client: FlaskClient, clock: FakeClock
) -> None:
    now = H9 + timedelta(days=2, minutes=30)
    expiring = H9 + timedelta(minutes=10)
    submit(client, clock, H9 + timedelta(days=1), station_id="ST-A", timestamp=iso(expiring))
    submit_hour(client, clock, now, "ST-A", now.replace(minute=0) - HOUR)
    clock.now = now

    run_forever(app, OneCycle())

    with app.app_context():
        assert db.session.get(ScoringRunRecord, SCORING_RUN_RECORD_ID) is not None
        assert expiring not in db.session.scalars(select(HealthReport.timestamp))
    assert summaries(app) == [(now.replace(minute=0) - HOUR, "ST-A")]
