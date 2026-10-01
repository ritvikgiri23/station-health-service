"""The metrics trend: GET /metrics/trend (role `read`), built from hourly summaries."""

from datetime import datetime, timedelta
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import insert

from station_health.extensions import db
from station_health.summaries.models import HourlySummary
from tests.support import ADMIN_KEY, INGEST_KEY, READ_KEY, START, FakeClock, auth, iso

HOUR = timedelta(hours=1)
H9, H10, H11 = START - 3 * HOUR, START - 2 * HOUR, START - HOUR


def register(client: FlaskClient, station_id: str, region: str) -> None:
    response = client.put(
        f"/stations/{station_id}", json={"region": region}, headers=auth(ADMIN_KEY)
    )
    assert response.status_code in (200, 201), response.json


def add_summary(
    app: Flask, station_id: str, hour_start: datetime, score: float, online: int, p95: float
) -> None:
    """A summary of 12 Health Reports, `online` of them online."""
    with app.app_context():
        db.session.execute(
            insert(HourlySummary),
            {
                "hour_start": hour_start,
                "station_id": station_id,
                "report_count": 12,
                "online_count": online,
                "average_latency_ms": p95,
                "max_latency_ms": p95,
                "p95_latency_ms": p95,
                "error_count_sum": 0,
                "average_hygiene_score": score,
            },
        )
        db.session.commit()


def trend(client: FlaskClient, **params: Any) -> Any:
    response = client.get("/metrics/trend", query_string=params, headers=auth(READ_KEY))
    assert response.status_code == 200, response.json
    return response.json


def point(
    hour: datetime,
    stations: int,
    below: int,
    score: float | None,
    availability: float | None,
    p95: float | None,
) -> dict[str, Any]:
    return {
        "hour": iso(hour),
        "reporting_station_count": stations,
        "below_flag_threshold_count": below,
        "average_hygiene_score": approx(score),
        "average_availability": approx(availability),
        "average_p95_latency_ms": approx(p95),
    }


def approx(value: float | None) -> Any:
    return None if value is None else pytest.approx(value)


def empty(hour: datetime) -> dict[str, Any]:
    return point(hour, 0, 0, None, None, None)


@pytest.fixture
def history(app: Flask, client: FlaskClient, clock: FakeClock) -> None:
    """Summaries for the three hours before 12:00, read at 12:10:

    - ST-N1 (north): 09:00 score 100, all online, p95 100; 10:00 score 70, 9 of 12 online,
      p95 140; no Health Reports at 11:00
    - ST-N2 (north): 10:00 score 40, all online, p95 200; 11:00 score 80, all online, p95 120
    - ST-X, no longer registered: 11:00 score 20, 3 of 12 online, p95 300
    - ST-N1 at 08:00, outside the requested hours
    """
    register(client, "ST-N1", "north")
    register(client, "ST-N2", "north")
    add_summary(app, "ST-N1", H9 - HOUR, score=0, online=0, p95=999)
    add_summary(app, "ST-N1", H9, score=100, online=12, p95=100)
    add_summary(app, "ST-N1", H10, score=70, online=9, p95=140)
    add_summary(app, "ST-N2", H10, score=40, online=12, p95=200)
    add_summary(app, "ST-N2", H11, score=80, online=12, p95=120)
    add_summary(app, "ST-X", H11, score=20, online=3, p95=300)
    clock.now = START + timedelta(minutes=10)


@pytest.mark.usefixtures("history")
def test_the_trend_has_a_point_for_each_completed_hour_requested(client: FlaskClient) -> None:
    body = trend(client, hours=3)

    assert body["hours"] == 3
    assert body["group_by"] is None
    assert body["groups"] is None
    # Averages are over the Stations that reported in the hour; a Station's Availability is
    # its online share. ST-N2's 40 is below the Flag Threshold (60), as is ST-X's 20.
    assert body["points"] == [
        point(H9, 1, 0, score=100, availability=1, p95=100),
        point(H10, 2, 1, score=(70 + 40) / 2, availability=(0.75 + 1) / 2, p95=(140 + 200) / 2),
        point(H11, 2, 1, score=(80 + 20) / 2, availability=(1 + 0.25) / 2, p95=(120 + 300) / 2),
    ]


@pytest.mark.usefixtures("history")
def test_hours_without_summaries_are_empty_points(client: FlaskClient) -> None:
    points = trend(client, hours=5)["points"]

    assert [p["hour"] for p in points] == [iso(START - n * HOUR) for n in range(5, 0, -1)]
    assert points[0] == empty(START - 5 * HOUR)
    assert points[1]["reporting_station_count"] == 1


@pytest.mark.usefixtures("history")
def test_grouped_by_region_each_region_has_a_full_series(client: FlaskClient) -> None:
    body = trend(client, hours=3, group_by="region")

    assert body["group_by"] == "region"
    assert len(body["points"]) == 3
    # The Region is the Station's current one; ST-X is no longer registered.
    assert body["groups"] == [
        {
            "key": "north",
            "points": [
                point(H9, 1, 0, score=100, availability=1, p95=100),
                point(H10, 2, 1, score=55, availability=0.875, p95=170),
                point(H11, 1, 0, score=80, availability=1, p95=120),
            ],
        },
        {
            "key": "unassigned",
            "points": [
                empty(H9),
                empty(H10),
                point(H11, 1, 1, score=20, availability=0.25, p95=300),
            ],
        },
    ]


def test_the_trend_defaults_to_the_past_24_hours(client: FlaskClient, clock: FakeClock) -> None:
    clock.now = START

    points = trend(client)["points"]

    assert len(points) == 24
    assert points[0]["hour"] == iso(START - 24 * HOUR)
    assert points[-1]["hour"] == iso(START - HOUR)


@pytest.mark.parametrize("hours", [0, -1, 30 * 24 + 1])
def test_hours_must_be_within_summary_retention(client: FlaskClient, hours: int) -> None:
    response = client.get("/metrics/trend", query_string={"hours": hours}, headers=auth(READ_KEY))

    assert response.status_code == 422


def test_an_unknown_grouping_is_rejected(client: FlaskClient) -> None:
    response = client.get(
        "/metrics/trend", query_string={"group_by": "firmware_version"}, headers=auth(READ_KEY)
    )

    assert response.status_code == 422


def test_the_trend_needs_the_read_role(client: FlaskClient) -> None:
    assert client.get("/metrics/trend").status_code == 401
    assert client.get("/metrics/trend", headers=auth(INGEST_KEY)).status_code == 403
