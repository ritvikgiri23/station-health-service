import json
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from flask.testing import FlaskClient

from station_health.app import create_app
from station_health.config import Settings
from station_health.worker.scoring_run import ScoringRun
from tests.support import START, FakeClock, iso

RunWorker = Callable[[datetime], ScoringRun]


@pytest.fixture
def unreachable_db_client() -> FlaskClient:
    # Nothing listens on port 1, so the connection is refused immediately.
    settings = Settings.from_env(
        {"DATABASE_URL": "mysql+pymysql://user:pass@127.0.0.1:1/none", "LOG_LEVEL": "CRITICAL"}
    )
    return create_app(settings).test_client()


def test_liveness_reports_ok(client: FlaskClient) -> None:
    response = client.get("/livez")

    assert response.status_code == 200
    assert response.json == {"status": "ok"}


def test_readiness_passes_when_the_database_is_reachable_and_scores_are_fresh(
    client: FlaskClient, clock: FakeClock, run_worker: RunWorker
) -> None:
    run_worker(START)
    clock.now = START + timedelta(minutes=3)

    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json == {
        "status": "ok",
        "checks": {"database": "ok", "scoring": "ok"},
        "scored_at": iso(START),
    }


def test_readiness_reports_degraded_when_the_last_scoring_run_is_over_3_minutes_old(
    client: FlaskClient, clock: FakeClock, run_worker: RunWorker
) -> None:
    run_worker(START)
    clock.now = START + timedelta(minutes=3, seconds=1)

    response = client.get("/readyz")

    # Still ready: the API itself serves; only its scores are old.
    assert response.status_code == 200
    assert response.json == {
        "status": "degraded",
        "checks": {"database": "ok", "scoring": "stale"},
        "scored_at": iso(START),
    }


def test_readiness_reports_degraded_before_any_scoring_run(client: FlaskClient) -> None:
    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json == {
        "status": "degraded",
        "checks": {"database": "ok", "scoring": "never_run"},
        "scored_at": None,
    }


def test_the_stale_score_threshold_is_configurable(
    make_client: Callable[..., FlaskClient], run_worker: RunWorker
) -> None:
    run_worker(START - timedelta(seconds=31))
    client = make_client(SCORING_STALE_AFTER_SECONDS="30")

    response = client.get("/readyz")

    assert response.json["status"] == "degraded"
    assert response.json["checks"]["scoring"] == "stale"


def test_readiness_fails_when_database_is_unreachable(
    unreachable_db_client: FlaskClient,
) -> None:
    response = unreachable_db_client.get("/readyz")

    assert response.status_code == 503
    assert response.json == {
        "status": "unavailable",
        "checks": {"database": "unreachable", "scoring": "unknown"},
        "scored_at": None,
    }


def test_liveness_does_not_depend_on_the_database(
    unreachable_db_client: FlaskClient,
) -> None:
    assert unreachable_db_client.get("/livez").status_code == 200


def test_each_response_carries_a_generated_request_id(client: FlaskClient) -> None:
    first = client.get("/livez").headers.get("X-Request-ID")
    second = client.get("/livez").headers.get("X-Request-ID")

    assert first
    assert second
    assert first != second


def test_a_caller_supplied_request_id_is_echoed(client: FlaskClient) -> None:
    response = client.get("/livez", headers={"X-Request-ID": "abc-123"})

    assert response.headers["X-Request-ID"] == "abc-123"


def test_an_unsafe_caller_supplied_request_id_is_replaced(client: FlaskClient) -> None:
    response = client.get("/livez", headers={"X-Request-ID": "bad id\twith spaces"})

    assert response.headers["X-Request-ID"] != "bad id\twith spaces"
    assert response.headers["X-Request-ID"]


def test_logs_are_json_lines_carrying_the_request_id(
    settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    client = create_app(replace(settings, log_level="INFO")).test_client()
    capsys.readouterr()

    client.get("/livez", headers={"X-Request-ID": "req-42"})

    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    records = [json.loads(line) for line in lines]
    request_log = next(r for r in records if r.get("path") == "/livez")
    assert request_log["request_id"] == "req-42"
    assert request_log["status"] == 200
    assert request_log["level"] == "INFO"
    assert "timestamp" in request_log
