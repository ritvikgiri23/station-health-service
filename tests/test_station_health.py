"""A Station's health status: GET /stations/{station_id}/health (role `read`)."""

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import pytest
from flask.testing import FlaskClient

from station_health.worker.scoring_run import ScoringRun, run_scoring_once
from tests.support import ADMIN_KEY, INGEST_KEY, READ_KEY, START, auth, health_report, iso

RunWorker = Callable[[datetime], ScoringRun]


def submit(client: FlaskClient, **fields: Any) -> None:
    response = client.post(
        "/health-reports", json=health_report(**fields), headers=auth(INGEST_KEY)
    )
    assert response.status_code == 201, response.json


def minutes_before_start(minutes: float) -> str:
    return iso(START - timedelta(minutes=minutes))


def station_health(client: FlaskClient, station_id: str = "ST-0001") -> Any:
    return client.get(f"/stations/{station_id}/health", headers=auth(READ_KEY))


def test_a_scoring_run_scores_a_station_from_its_health_reports_in_the_window(
    client: FlaskClient, run_worker: RunWorker
) -> None:
    # 15 Probes a minute apart: 1 Offline, then online at 300 ms with 7 errors in total.
    submit(client, timestamp=minutes_before_start(14), connectivity_status="offline")
    for minute in range(13, -1, -1):
        submit(
            client,
            timestamp=minutes_before_start(minute),
            latency_ms=300,
            error_count=minute % 2,
            firmware_version="2.0.1",
        )

    run_worker(START)

    response = station_health(client)
    assert response.status_code == 200
    body = response.json
    assert body == {
        "station_id": "ST-0001",
        "region": None,
        "verified": False,
        "latest_report": {
            "timestamp": iso(START),
            "connectivity_status": "online",
            "latency_ms": 300.0,
            "error_count": 0,
            "firmware_version": "2.0.1",
        },
        "hygiene": body["hygiene"],
        "scored_at": iso(START),
    }
    assert body["hygiene"] == {
        "score": 77,
        "availability": pytest.approx(14 / 15),
        "latency_score": pytest.approx(700 / 850),
        "error_score": pytest.approx(1 - 0.5 / 3),
        "p95_latency_ms": 300.0,
        "report_count": 15,
        "silent": False,
        "poor_hygiene": False,
        "flag_reason": None,
        "flagged_since": None,
    }


def test_before_any_scoring_run_a_station_has_its_latest_report_but_no_score(
    client: FlaskClient,
) -> None:
    submit(client, timestamp=minutes_before_start(1))

    body = station_health(client).json

    assert body["latest_report"]["timestamp"] == minutes_before_start(1)
    assert body["hygiene"] is None
    assert body["scored_at"] is None


def test_only_health_reports_in_the_scoring_window_are_scored(
    client: FlaskClient, run_worker: RunWorker
) -> None:
    # The window ending at START is (START - 15 min, START].
    submit(client, timestamp=minutes_before_start(15), connectivity_status="offline")
    submit(client, timestamp=minutes_before_start(14.9))
    submit(client, timestamp=minutes_before_start(0))
    submit(client, timestamp=minutes_before_start(-1), connectivity_status="offline")

    run_worker(START)

    hygiene = station_health(client).json["hygiene"]
    assert hygiene["report_count"] == 2
    assert hygiene["availability"] == 1.0


def test_a_late_arriving_older_health_report_never_replaces_the_latest(
    client: FlaskClient, run_worker: RunWorker
) -> None:
    submit(client, timestamp=minutes_before_start(1), firmware_version="2.0.0")
    submit(client, timestamp=minutes_before_start(9), firmware_version="1.9.9")

    run_worker(START)

    body = station_health(client).json
    assert body["latest_report"]["timestamp"] == minutes_before_start(1)
    assert body["latest_report"]["firmware_version"] == "2.0.0"
    # The late Health Report still counts in its Scoring Window.
    assert body["hygiene"]["report_count"] == 2


def test_each_scoring_run_rescores_from_its_own_window_and_updates_scored_at(
    client: FlaskClient, run_worker: RunWorker
) -> None:
    for minute in range(10):
        submit(client, timestamp=minutes_before_start(minute))
    run_worker(START)
    assert station_health(client).json["hygiene"]["score"] == 100

    # Five minutes later the Station has been Offline for every new Probe.
    for minute in range(1, 6):
        submit(client, timestamp=minutes_before_start(-minute), connectivity_status="offline")
    later = START + timedelta(minutes=5)
    run_worker(later)

    body = station_health(client).json
    assert body["hygiene"]["report_count"] == 15
    assert body["hygiene"]["availability"] == pytest.approx(10 / 15)
    assert body["hygiene"]["score"] == 67
    assert body["scored_at"] == iso(later)


def test_one_scoring_run_scores_every_registered_station(
    client: FlaskClient, run_worker: RunWorker
) -> None:
    submit(client, station_id="ST-FAST", latency_ms=100)
    submit(client, station_id="ST-ERRORS", latency_ms=100, error_count=3)
    submit(client, station_id="ST-OLD", timestamp=minutes_before_start(30))

    run = run_worker(START)

    assert run.stations_scored == 3
    assert run.scored_at == START
    assert station_health(client, "ST-FAST").json["hygiene"]["score"] == 100
    assert station_health(client, "ST-ERRORS").json["hygiene"]["score"] == 40
    # Nothing in its window: Silent.
    old = station_health(client, "ST-OLD").json["hygiene"]
    assert old["silent"] is True
    assert old["score"] is None


def test_a_station_offline_all_window_scores_0_without_latency_or_error_scores(
    client: FlaskClient, run_worker: RunWorker
) -> None:
    for minute in range(3):
        submit(client, timestamp=minutes_before_start(minute), connectivity_status="offline")

    run_worker(START)

    assert station_health(client).json["hygiene"] == {
        "score": 0,
        "availability": 0.0,
        "latency_score": None,
        "error_score": None,
        "p95_latency_ms": None,
        "report_count": 3,
        "silent": False,
        "poor_hygiene": True,
        "flag_reason": "availability",
        "flagged_since": iso(START),
    }


def test_the_scoring_window_and_scoring_limits_are_configurable(
    make_client: Callable[..., FlaskClient],
) -> None:
    client = make_client(SCORING_WINDOW_MINUTES="5", LATENCY_GOOD_MS="100", LATENCY_BAD_MS="500")
    submit(client, timestamp=minutes_before_start(10), connectivity_status="offline")
    submit(client, timestamp=minutes_before_start(1), latency_ms=300)

    with client.application.app_context():
        run_scoring_once(START)

    hygiene = station_health(client).json["hygiene"]
    assert hygiene["report_count"] == 1
    assert hygiene["latency_score"] == 0.5


def test_an_unknown_station_is_not_found(client: FlaskClient) -> None:
    response = station_health(client, "ST-TYPO")

    assert response.status_code == 404
    assert response.json["code"] == 404


@pytest.mark.parametrize("key", [INGEST_KEY, ADMIN_KEY])
def test_station_health_requires_the_read_role(client: FlaskClient, key: str) -> None:
    assert client.get("/stations/ST-0001/health").status_code == 401
    assert client.get("/stations/ST-0001/health", headers=auth(key)).status_code == 403
