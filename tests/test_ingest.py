"""Ingesting Health Reports: POST /health-reports (role `ingest`)."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient

from tests.support import ADMIN_KEY, INGEST_KEY, START, auth, health_report, iso


def submit(client: FlaskClient, payload: dict[str, Any], key: str = INGEST_KEY) -> Any:
    return client.post("/health-reports", json=payload, headers=auth(key))


def registry_entry(client: FlaskClient, station_id: str) -> Any:
    return client.get(f"/stations/{station_id}", headers=auth(ADMIN_KEY))


def test_a_new_health_report_is_stored_and_returned(client: FlaskClient) -> None:
    payload = health_report()

    response = submit(client, payload)

    assert response.status_code == 201
    assert response.json == payload


def test_resubmitting_the_same_station_and_timestamp_returns_200_without_a_second_record(
    client: FlaskClient,
) -> None:
    original = health_report(latency_ms=120.7)
    submit(client, original)

    retry = submit(client, original)
    conflicting = submit(client, health_report(latency_ms=999.0, error_count=7))

    assert retry.status_code == 200
    assert retry.json == original
    # First write wins: a second report for the same key is not stored.
    assert conflicting.status_code == 200
    assert conflicting.json == original


def test_timestamps_with_other_offsets_are_normalised_to_utc(client: FlaskClient) -> None:
    response = submit(client, health_report(timestamp="2026-10-01T17:29:00+05:30"))

    assert response.status_code == 201
    assert response.json["timestamp"] == "2026-10-01T11:59:00+00:00"
    # The same instant written with a different offset is the same Health Report.
    assert submit(client, health_report(timestamp="2026-10-01T11:59:00Z")).status_code == 200


def test_an_offline_health_report_is_accepted(client: FlaskClient) -> None:
    response = submit(client, health_report(connectivity_status="offline", latency_ms=5000))

    assert response.status_code == 201


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("station_id", 42),
        ("station_id", ""),
        ("station_id", "x" * 65),
        ("timestamp", "yesterday"),
        ("timestamp", "2026-10-01T11:59:00"),  # no timezone offset
        ("connectivity_status", "degraded"),
        ("connectivity_status", "ONLINE"),
        ("latency_ms", "fast"),
        ("latency_ms", -1),
        ("latency_ms", True),
        ("error_count", -1),
        ("error_count", 1.5),
        ("error_count", "3"),
        ("error_count", True),
        ("error_count", 2**32),
        ("firmware_version", 1.4),
        ("firmware_version", ""),
    ],
)
def test_malformed_fields_are_rejected_with_422(
    client: FlaskClient, field: str, value: Any
) -> None:
    response = submit(client, health_report(**{field: value}))

    assert response.status_code == 422
    assert response.json["code"] == 422
    assert field in response.json["errors"]["json"]


@pytest.mark.parametrize(
    "field",
    [
        "station_id",
        "timestamp",
        "connectivity_status",
        "latency_ms",
        "error_count",
        "firmware_version",
    ],
)
def test_missing_fields_are_rejected_with_422(client: FlaskClient, field: str) -> None:
    payload = health_report()
    del payload[field]

    response = submit(client, payload)

    assert response.status_code == 422
    assert field in response.json["errors"]["json"]


def test_unknown_fields_are_rejected_with_422(client: FlaskClient) -> None:
    response = submit(client, health_report(boot_id="abc"))

    assert response.status_code == 422
    assert "boot_id" in response.json["errors"]["json"]


def test_a_body_that_is_not_json_is_rejected_with_400(client: FlaskClient) -> None:
    response = client.post(
        "/health-reports",
        data="not json",
        content_type="application/json",
        headers=auth(INGEST_KEY),
    )

    # Unparseable JSON is a bad request rather than an invalid Health Report.
    assert response.status_code == 400
    assert response.json["code"] == 400


def test_a_timestamp_more_than_five_minutes_in_the_future_is_rejected(
    client: FlaskClient,
) -> None:
    at_limit = submit(client, health_report(timestamp=iso(START + timedelta(minutes=5))))
    beyond = submit(client, health_report(timestamp=iso(START + timedelta(minutes=5, seconds=1))))

    assert at_limit.status_code == 201
    assert beyond.status_code == 422
    assert "timestamp" in beyond.json["errors"]["json"]


def test_a_timestamp_older_than_raw_retention_is_rejected(client: FlaskClient) -> None:
    within = submit(client, health_report(timestamp=iso(START - timedelta(hours=48))))
    beyond = submit(client, health_report(timestamp=iso(START - timedelta(hours=48, seconds=1))))

    assert within.status_code == 201
    assert beyond.status_code == 422
    assert "timestamp" in beyond.json["errors"]["json"]


def test_the_future_tolerance_and_raw_retention_are_configurable(
    make_client: Callable[..., FlaskClient],
) -> None:
    client = make_client(INGEST_FUTURE_TOLERANCE_SECONDS="60", RAW_RETENTION_HOURS="1")

    future = submit(client, health_report(timestamp=iso(START + timedelta(minutes=2))))
    old = submit(client, health_report(timestamp=iso(START - timedelta(hours=2))))

    assert future.status_code == 422
    assert old.status_code == 422


def test_late_and_out_of_order_health_reports_are_stored(client: FlaskClient) -> None:
    newest = health_report(timestamp=iso(START - timedelta(minutes=1)))
    older = health_report(timestamp=iso(START - timedelta(minutes=30)))
    much_older = health_report(timestamp=iso(START - timedelta(hours=20)))

    assert submit(client, newest).status_code == 201
    assert submit(client, older).status_code == 201
    assert submit(client, much_older).status_code == 201
    # Each was stored: resubmitting is now a duplicate.
    assert [submit(client, r).status_code for r in (newest, older, much_older)] == [200] * 3


def test_a_health_report_for_an_unregistered_station_registers_an_unverified_station(
    client: FlaskClient,
) -> None:
    assert registry_entry(client, "ST-NEW").status_code == 404

    submit(client, health_report(station_id="ST-NEW"))

    response = registry_entry(client, "ST-NEW")
    assert response.status_code == 200
    assert response.json == {"station_id": "ST-NEW", "region": None, "verified": False}


def test_further_health_reports_leave_the_station_registered_once(client: FlaskClient) -> None:
    submit(client, health_report(station_id="ST-NEW", timestamp=iso(START - timedelta(minutes=2))))
    submit(client, health_report(station_id="ST-NEW", timestamp=iso(START - timedelta(minutes=1))))

    response = registry_entry(client, "ST-NEW")
    assert response.status_code == 200
    assert response.json == {"station_id": "ST-NEW", "region": None, "verified": False}


def test_concurrent_retries_of_a_new_stations_first_health_report_store_it_once(
    app: Flask,
) -> None:
    payload = health_report(station_id="ST-RACE")

    def attempt(_: int) -> int:
        status: int = submit(app.test_client(), payload).status_code
        return status

    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses = list(pool.map(attempt, range(16)))

    assert sorted(statuses) == [200] * 15 + [201]
    assert registry_entry(app.test_client(), "ST-RACE").json["verified"] is False
