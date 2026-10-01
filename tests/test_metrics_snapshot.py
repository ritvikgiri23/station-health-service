"""The metrics snapshot: GET /metrics (role `read`)."""

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import pytest
from flask.testing import FlaskClient

from station_health.worker.scoring_run import ScoringRun
from tests.support import ADMIN_KEY, INGEST_KEY, READ_KEY, START, auth, health_report, iso

RunWorker = Callable[[datetime], ScoringRun]

T0 = START


def submit_scoring(
    client: FlaskClient, station_id: str, score: int, latency_ms: float, firmware: str
) -> None:
    """Submit Health Reports that score `score` (a multiple of 10) on Availability alone.

    Every latency is within the good limit, so the latency score stays 1 and the online
    Health Reports' p95 latency is `latency_ms`.
    """
    online = score // 10
    for minute in range(10):
        submit(
            client,
            station_id=station_id,
            timestamp=iso(T0 - timedelta(minutes=minute)),
            connectivity_status="online" if minute < online else "offline",
            latency_ms=latency_ms,
            firmware_version=firmware,
        )


def submit(client: FlaskClient, **fields: Any) -> None:
    response = client.post(
        "/health-reports", json=health_report(**fields), headers=auth(INGEST_KEY)
    )
    assert response.status_code == 201, response.json


def register(client: FlaskClient, station_id: str, region: str) -> None:
    """Register a Station in a Region, which also marks it verified."""
    response = client.put(
        f"/stations/{station_id}", json={"region": region}, headers=auth(ADMIN_KEY)
    )
    assert response.status_code in (200, 201), response.json


def metrics(client: FlaskClient, **params: Any) -> Any:
    response = client.get("/metrics", query_string=params, headers=auth(READ_KEY))
    assert response.status_code == 200, response.json
    return response.json


def figures(
    stations: int,
    poor: int,
    silent: int,
    unverified: int,
    score: float | None,
    availability: float | None,
    p95: float | None,
) -> dict[str, Any]:
    return {
        "station_count": stations,
        "poor_hygiene_count": poor,
        "poor_hygiene_percentage": pytest.approx(100 * poor / stations),
        "silent_count": silent,
        "unverified_count": unverified,
        "average_hygiene_score": approx(score),
        "average_availability": approx(availability),
        "average_p95_latency_ms": approx(p95),
    }


def approx(value: float | None) -> Any:
    return None if value is None else pytest.approx(value)


@pytest.fixture
def fleet(client: FlaskClient, run_worker: RunWorker) -> None:
    """A known fleet, scored at T0:

    - ST-N1: north, firmware 1.0, score 100, p95 100 ms
    - ST-N2: north, firmware 2.0, score 50 (Poor Hygiene), p95 140 ms
    - ST-S1: south, Silent (its one Health Report is too old), firmware unreported
    - ST-S2: south, registered after the scoring run, so not yet scored
    - ST-U1: no Region, Unverified, firmware 1.0, score 100, p95 120 ms
    """
    register(client, "ST-N1", "north")
    register(client, "ST-N2", "north")
    register(client, "ST-S1", "south")
    submit_scoring(client, "ST-N1", 100, latency_ms=100, firmware="1.0")
    submit_scoring(client, "ST-N2", 50, latency_ms=140, firmware="2.0")
    submit(client, station_id="ST-S1", timestamp=iso(T0 - timedelta(minutes=30)))
    submit_scoring(client, "ST-U1", 100, latency_ms=120, firmware="1.0")
    run_worker(T0)
    register(client, "ST-S2", "south")


@pytest.mark.usefixtures("fleet")
def test_the_overall_snapshot_covers_the_whole_station_registry(client: FlaskClient) -> None:
    body = metrics(client)

    assert body["group_by"] is None
    assert body["groups"] is None
    assert body["scored_at"] == iso(T0)
    # Averages are over the scored Stations; Silent and unscored ones have no score.
    assert body["overall"] == figures(
        stations=5,
        poor=2,
        silent=1,
        unverified=1,
        score=(100 + 50 + 100) / 3,
        availability=(1 + 0.5 + 1) / 3,
        p95=(100 + 140 + 120) / 3,
    )


@pytest.mark.usefixtures("fleet")
def test_grouped_by_region_stations_without_a_region_are_unassigned(client: FlaskClient) -> None:
    body = metrics(client, group_by="region")

    assert body["group_by"] == "region"
    assert body["overall"]["station_count"] == 5
    assert body["groups"] == [
        {"key": "north", **figures(2, 1, 0, 0, score=75, availability=0.75, p95=120)},
        {"key": "south", **figures(2, 1, 1, 0, score=None, availability=None, p95=None)},
        {"key": "unassigned", **figures(1, 0, 0, 1, score=100, availability=1, p95=120)},
    ]


@pytest.mark.usefixtures("fleet")
def test_grouped_by_firmware_version_from_each_stations_latest_health_report(
    client: FlaskClient,
) -> None:
    body = metrics(client, group_by="firmware_version")

    assert body["group_by"] == "firmware_version"
    assert body["groups"] == [
        {"key": "1.0", **figures(2, 0, 0, 1, score=100, availability=1, p95=110)},
        {"key": "2.0", **figures(1, 1, 0, 0, score=50, availability=0.5, p95=140)},
        {"key": "unreported", **figures(2, 1, 1, 0, score=None, availability=None, p95=None)},
    ]


def test_firmware_version_follows_upgrades_and_is_kept_while_silent(
    client: FlaskClient, run_worker: RunWorker
) -> None:
    submit(client, station_id="ST-1", timestamp=iso(T0 - timedelta(minutes=2)))
    submit(
        client,
        station_id="ST-1",
        timestamp=iso(T0 - timedelta(minutes=1)),
        firmware_version="2.0",
    )
    # Arrives last but is older, so it is not the latest Health Report.
    submit(
        client,
        station_id="ST-1",
        timestamp=iso(T0 - timedelta(minutes=3)),
        firmware_version="0.9",
    )
    run_worker(T0)
    upgraded = metrics(client, group_by="firmware_version")["groups"]
    assert [group["key"] for group in upgraded] == ["2.0"]

    run_worker(T0 + timedelta(hours=1))

    silent = metrics(client, group_by="firmware_version")["groups"]
    assert [(group["key"], group["silent_count"]) for group in silent] == [("2.0", 1)]


def test_an_empty_fleet_has_zero_counts_and_no_averages(client: FlaskClient) -> None:
    body = metrics(client)

    assert body["scored_at"] is None
    assert body["overall"] == {
        "station_count": 0,
        "poor_hygiene_count": 0,
        "poor_hygiene_percentage": None,
        "silent_count": 0,
        "unverified_count": 0,
        "average_hygiene_score": None,
        "average_availability": None,
        "average_p95_latency_ms": None,
    }
    assert metrics(client, group_by="region")["groups"] == []


def test_an_unknown_grouping_is_rejected(client: FlaskClient) -> None:
    response = client.get("/metrics", query_string={"group_by": "city"}, headers=auth(READ_KEY))

    assert response.status_code == 422


def test_the_snapshot_needs_the_read_role(client: FlaskClient) -> None:
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers=auth(INGEST_KEY)).status_code == 403
