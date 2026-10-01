"""Station Registry management (role `admin`): register, update, verify, delete and list."""

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient

from station_health.worker.scoring_run import ScoringRun
from tests.support import ADMIN_KEY, INGEST_KEY, READ_KEY, START, auth, health_report, iso

RunWorker = Callable[[datetime], ScoringRun]


def put_station(client: FlaskClient, station_id: str, region: str | None) -> Any:
    return client.put(f"/stations/{station_id}", json={"region": region}, headers=auth(ADMIN_KEY))


def delete_station(client: FlaskClient, station_id: str) -> Any:
    return client.delete(f"/stations/{station_id}", headers=auth(ADMIN_KEY))


def submit(client: FlaskClient, **fields: Any) -> None:
    response = client.post(
        "/health-reports", json=health_report(**fields), headers=auth(INGEST_KEY)
    )
    assert response.status_code == 201, response.json


def poor_hygiene_ids(client: FlaskClient) -> list[str]:
    response = client.get("/poor-hygiene", headers=auth(READ_KEY))
    return [item["station_id"] for item in response.json["items"]]


def registry_entry(client: FlaskClient, station_id: str) -> Any:
    return client.get(f"/stations/{station_id}", headers=auth(ADMIN_KEY))


def test_registering_a_new_station_marks_it_verified(client: FlaskClient) -> None:
    response = put_station(client, "ST-0001", "eu-west")

    assert response.status_code == 201
    assert response.json == {"station_id": "ST-0001", "region": "eu-west", "verified": True}
    assert registry_entry(client, "ST-0001").json == response.json


def test_registering_again_updates_the_region_idempotently(client: FlaskClient) -> None:
    put_station(client, "ST-0001", "eu-west")

    moved = put_station(client, "ST-0001", "us-east")
    again = put_station(client, "ST-0001", "us-east")
    cleared = put_station(client, "ST-0001", None)

    assert (moved.status_code, again.status_code, cleared.status_code) == (200, 200, 200)
    assert again.json == {"station_id": "ST-0001", "region": "us-east", "verified": True}
    assert registry_entry(client, "ST-0001").json == {
        "station_id": "ST-0001",
        "region": None,
        "verified": True,
    }


def test_registering_an_unverified_station_confirms_it(client: FlaskClient) -> None:
    client.post(
        "/health-reports", json=health_report(station_id="ST-NEW"), headers=auth(INGEST_KEY)
    )
    assert registry_entry(client, "ST-NEW").json["verified"] is False

    response = put_station(client, "ST-NEW", "eu-west")

    assert response.status_code == 200
    assert registry_entry(client, "ST-NEW").json == {
        "station_id": "ST-NEW",
        "region": "eu-west",
        "verified": True,
    }


@pytest.mark.parametrize(
    "body",
    [{}, {"region": ""}, {"region": "r" * 65}, {"region": 7}, {"region": "eu", "verified": False}],
)
def test_an_invalid_registration_is_rejected_with_422(
    client: FlaskClient, body: dict[str, Any]
) -> None:
    response = client.put("/stations/ST-0001", json=body, headers=auth(ADMIN_KEY))

    assert response.status_code == 422
    assert registry_entry(client, "ST-0001").status_code == 404


def test_a_station_id_longer_than_64_characters_is_rejected(client: FlaskClient) -> None:
    assert put_station(client, "S" * 65, "eu-west").status_code == 422


@pytest.mark.parametrize("key", [INGEST_KEY, READ_KEY])
def test_registry_changes_need_the_admin_role(client: FlaskClient, key: str) -> None:
    put_station(client, "ST-0001", "eu-west")

    assert (
        client.put("/stations/ST-0001", json={"region": "us-east"}, headers=auth(key)).status_code
        == 403
    )
    assert client.delete("/stations/ST-0001", headers=auth(key)).status_code == 403
    assert client.get("/stations", headers=auth(key)).status_code == 403
    assert client.put("/stations/ST-0001", json={"region": "us-east"}).status_code == 401
    assert registry_entry(client, "ST-0001").json["region"] == "eu-west"


def test_a_registered_station_that_never_reports_is_silent_with_poor_hygiene(
    client: FlaskClient, run_worker: RunWorker
) -> None:
    put_station(client, "ST-QUIET", "eu-west")

    run_worker(START)

    hygiene = client.get("/stations/ST-QUIET/health", headers=auth(READ_KEY)).json["hygiene"]
    assert hygiene["silent"] is True
    assert hygiene["poor_hygiene"] is True
    assert hygiene["flag_reason"] == "silent"
    assert poor_hygiene_ids(client) == ["ST-QUIET"]


def test_a_deleted_station_leaves_the_registry_and_stops_being_scored(
    client: FlaskClient, run_worker: RunWorker
) -> None:
    put_station(client, "ST-BAD-ID", None)
    run_worker(START)
    assert poor_hygiene_ids(client) == ["ST-BAD-ID"]

    response = delete_station(client, "ST-BAD-ID")

    assert response.status_code == 204
    assert registry_entry(client, "ST-BAD-ID").status_code == 404
    assert client.get("/stations/ST-BAD-ID/health", headers=auth(READ_KEY)).status_code == 404
    run = run_worker(START + timedelta(minutes=1))
    assert run.stations_scored == 0
    assert poor_hygiene_ids(client) == []


def test_deleting_an_unknown_station_is_404(client: FlaskClient) -> None:
    assert delete_station(client, "ST-NOPE").status_code == 404


def test_a_station_registered_again_after_deletion_starts_afresh(
    client: FlaskClient, run_worker: RunWorker
) -> None:
    put_station(client, "ST-0001", "eu-west")
    run_worker(START)
    delete_station(client, "ST-0001")

    # A new Health Report registers it again, as an Unverified Station.
    later = START + timedelta(minutes=2)
    for minute in range(5):
        submit(client, station_id="ST-0001", timestamp=iso(later - timedelta(minutes=minute)))
    run_worker(later)

    body = client.get("/stations/ST-0001/health", headers=auth(READ_KEY)).json
    assert body["verified"] is False
    assert body["region"] is None
    # Not still flagged from its Silent spell before deletion.
    assert body["hygiene"]["poor_hygiene"] is False
    assert body["hygiene"]["flagged_since"] is None


def list_stations(client: FlaskClient, **params: Any) -> Any:
    response = client.get("/stations", query_string=params, headers=auth(ADMIN_KEY))
    assert response.status_code == 200, response.json
    return response.json


def test_lists_stations_by_station_id_filterable_to_unverified(client: FlaskClient) -> None:
    put_station(client, "ST-B", "eu-west")
    submit(client, station_id="ST-C")
    put_station(client, "ST-A", None)
    submit(client, station_id="ST-D")

    everything = list_stations(client)
    unverified = list_stations(client, verified="false")
    verified = list_stations(client, verified="true")

    assert everything == {
        "items": [
            {"station_id": "ST-A", "region": None, "verified": True},
            {"station_id": "ST-B", "region": "eu-west", "verified": True},
            {"station_id": "ST-C", "region": None, "verified": False},
            {"station_id": "ST-D", "region": None, "verified": False},
        ],
        "next_cursor": None,
    }
    assert [s["station_id"] for s in unverified["items"]] == ["ST-C", "ST-D"]
    assert [s["station_id"] for s in verified["items"]] == ["ST-A", "ST-B"]


def test_the_station_list_is_cursor_paged(client: FlaskClient) -> None:
    for number in range(5):
        put_station(client, f"ST-{number}", None)
    submit(client, station_id="ST-2-UNVERIFIED")

    pages = [list_stations(client, limit=2)]
    while pages[-1]["next_cursor"] is not None:
        pages.append(list_stations(client, limit=2, cursor=pages[-1]["next_cursor"]))
    unverified = list_stations(client, verified="false", limit=1)

    assert [[s["station_id"] for s in page["items"]] for page in pages] == [
        ["ST-0", "ST-1"],
        ["ST-2", "ST-2-UNVERIFIED"],
        ["ST-3", "ST-4"],
    ]
    assert [s["station_id"] for s in unverified["items"]] == ["ST-2-UNVERIFIED"]
    assert unverified["next_cursor"] is None


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 501}])
def test_station_list_paging_limits(client: FlaskClient, params: dict[str, Any]) -> None:
    assert client.get("/stations", query_string=params, headers=auth(ADMIN_KEY)).status_code == 422


def test_a_malformed_station_list_cursor_is_rejected(client: FlaskClient) -> None:
    response = client.get("/stations", query_string={"cursor": "%%%"}, headers=auth(ADMIN_KEY))

    assert response.status_code == 400


def test_the_seed_command_registers_stations_across_regions(
    app: Flask, client: FlaskClient
) -> None:
    result = app.test_cli_runner().invoke(args=["seed-stations", "--count", "12"])

    assert result.exit_code == 0, result.output
    assert "12 Stations" in result.output
    stations = list_stations(client, limit=500)["items"]
    assert len(stations) == 12
    assert stations[0] == {"station_id": "ST-000001", "region": "us-west", "verified": True}
    assert all(station["verified"] for station in stations)
    assert len({station["region"] for station in stations}) == 5


def test_seeding_again_is_idempotent_and_verifies_seen_stations(
    app: Flask, client: FlaskClient
) -> None:
    submit(client, station_id="ST-000002")
    runner = app.test_cli_runner()

    runner.invoke(args=["seed-stations", "--count", "3"])
    result = runner.invoke(args=["seed-stations", "--count", "3"])

    assert result.exit_code == 0, result.output
    stations = list_stations(client)["items"]
    assert [s["station_id"] for s in stations] == ["ST-000001", "ST-000002", "ST-000003"]
    assert registry_entry(client, "ST-000002").json["verified"] is True


def test_the_seed_count_must_be_positive(app: Flask) -> None:
    result = app.test_cli_runner().invoke(args=["seed-stations", "--count", "0"])

    assert result.exit_code != 0


def test_a_deleted_stations_health_reports_remain_and_count_if_it_returns(
    client: FlaskClient, run_worker: RunWorker
) -> None:
    for minute in range(5):
        submit(client, station_id="ST-0001", timestamp=iso(START - timedelta(minutes=minute)))
    assert delete_station(client, "ST-0001").status_code == 204

    response = put_station(client, "ST-0001", "eu-west")
    run_worker(START)

    assert response.status_code == 201
    body = client.get("/stations/ST-0001/health", headers=auth(READ_KEY)).json
    assert body["latest_report"]["timestamp"] == iso(START)
    assert body["hygiene"]["report_count"] == 5
    assert body["hygiene"]["silent"] is False
