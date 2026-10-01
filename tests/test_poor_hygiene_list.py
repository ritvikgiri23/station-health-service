"""The Poor Hygiene list: GET /poor-hygiene (role `read`)."""

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import update

from station_health.extensions import db
from station_health.stations.models import Station
from station_health.worker.scoring_run import ScoringRun
from tests.support import INGEST_KEY, READ_KEY, START, auth, health_report, iso

RunWorker = Callable[[datetime], ScoringRun]

# Scoring runs a minute apart. Every Health Report below is timestamped just before T0,
# so it stays in the Scoring Window of both runs and a Station scores the same in each.
T0 = START
# Microseconds, so cursors must carry "flagged since" at full precision.
T1 = START + timedelta(minutes=1, microseconds=250_000)


def submit_scoring(client: FlaskClient, station_id: str, score: int) -> None:
    """Submit Health Reports that score `score` (a multiple of 10) on Availability alone."""
    online = score // 10
    for minute in range(10):
        submit(
            client,
            station_id=station_id,
            timestamp=iso(T0 - timedelta(minutes=minute)),
            connectivity_status="online" if minute < online else "offline",
        )


def silence(client: FlaskClient, station_id: str) -> None:
    """Register a Station with one Health Report too old for the Scoring Window."""
    submit(client, station_id=station_id, timestamp=iso(T0 - timedelta(minutes=30)))


def set_registry_facts(app: Flask, station_id: str, region: str | None, verified: bool) -> None:
    """Set a Station's Region and verified. Test arrangement until the registry API exists."""
    with app.app_context():
        db.session.execute(
            update(Station)
            .where(Station.station_id == station_id)
            .values(region=region, verified=verified)
        )
        db.session.commit()


def submit(client: FlaskClient, **fields: Any) -> None:
    response = client.post(
        "/health-reports", json=health_report(**fields), headers=auth(INGEST_KEY)
    )
    assert response.status_code == 201, response.json


def poor_hygiene(client: FlaskClient, **params: Any) -> Any:
    response = client.get("/poor-hygiene", query_string=params, headers=auth(READ_KEY))
    assert response.status_code == 200, response.json
    return response.json


def station_ids(body: Any) -> list[str]:
    return [item["station_id"] for item in body["items"]]


def test_lists_only_stations_with_poor_hygiene_worst_first_with_silent_as_zero(
    client: FlaskClient, run_worker: RunWorker
) -> None:
    submit_scoring(client, "ST-HEALTHY", 100)
    submit_scoring(client, "ST-50", 50)
    submit_scoring(client, "ST-20", 20)
    silence(client, "ST-SILENT")
    submit_scoring(client, "ST-30", 30)

    run_worker(T0)

    body = poor_hygiene(client)
    assert station_ids(body) == ["ST-SILENT", "ST-20", "ST-30", "ST-50"]
    assert body["items"][0] == {
        "station_id": "ST-SILENT",
        "region": None,
        "verified": False,
        "score": None,
        "silent": True,
        "flag_reason": "silent",
        "flagged_since": iso(T0),
    }
    assert body["items"][1]["score"] == 20
    assert body["items"][1]["flag_reason"] == "availability"
    assert body["total"] == 4
    assert body["next_cursor"] is None
    assert body["scored_at"] == iso(T0)


def test_ties_on_score_go_to_the_oldest_flagged_since_then_station_id(
    client: FlaskClient, run_worker: RunWorker
) -> None:
    submit_scoring(client, "ST-ZERO", 0)
    submit_scoring(client, "ST-40-OLDER", 40)
    run_worker(T0)
    silence(client, "ST-SILENT")
    submit_scoring(client, "ST-40-NEWER-B", 40)
    submit_scoring(client, "ST-40-NEWER-A", 40)
    run_worker(T1)

    body = poor_hygiene(client)

    assert station_ids(body) == [
        # Silent sorts as 0, level with ST-ZERO, which was flagged first.
        "ST-ZERO",
        "ST-SILENT",
        "ST-40-OLDER",
        # Same score, same "flagged since": `station_id` decides.
        "ST-40-NEWER-A",
        "ST-40-NEWER-B",
    ]


def test_filters_by_region_flag_reason_and_verified(
    app: Flask, client: FlaskClient, run_worker: RunWorker
) -> None:
    submit_scoring(client, "ST-EU-VERIFIED", 30)
    submit_scoring(client, "ST-EU-UNVERIFIED", 20)
    silence(client, "ST-US-SILENT")
    submit_scoring(client, "ST-UNASSIGNED", 10)
    set_registry_facts(app, "ST-EU-VERIFIED", "eu-west", verified=True)
    set_registry_facts(app, "ST-EU-UNVERIFIED", "eu-west", verified=False)
    set_registry_facts(app, "ST-US-SILENT", "us-east", verified=True)
    run_worker(T0)

    by_region = poor_hygiene(client, region="eu-west")
    assert station_ids(by_region) == ["ST-EU-UNVERIFIED", "ST-EU-VERIFIED"]
    assert by_region["items"][0]["region"] == "eu-west"
    assert by_region["total"] == 2

    by_reason = poor_hygiene(client, flag_reason="silent")
    assert station_ids(by_reason) == ["ST-US-SILENT"]
    assert by_reason["total"] == 1
    assert poor_hygiene(client, flag_reason="availability")["total"] == 3
    assert poor_hygiene(client, flag_reason="errors")["total"] == 0

    verified = poor_hygiene(client, verified="true")
    assert station_ids(verified) == ["ST-US-SILENT", "ST-EU-VERIFIED"]
    unverified = poor_hygiene(client, verified="false")
    assert station_ids(unverified) == ["ST-UNASSIGNED", "ST-EU-UNVERIFIED"]
    assert unverified["total"] == 2

    combined = poor_hygiene(client, region="eu-west", verified="false")
    assert station_ids(combined) == ["ST-EU-UNVERIFIED"]
    assert combined["total"] == 1

    assert poor_hygiene(client, region="ap-south") == {
        "items": [],
        "total": 0,
        "next_cursor": None,
        "scored_at": iso(T0),
    }


def all_pages(client: FlaskClient, **params: Any) -> list[Any]:
    pages = [poor_hygiene(client, **params)]
    while pages[-1]["next_cursor"] is not None:
        pages.append(poor_hygiene(client, **params, cursor=pages[-1]["next_cursor"]))
    return pages


def test_cursor_paging_visits_every_station_once_in_order(
    client: FlaskClient, run_worker: RunWorker
) -> None:
    # Ties on score and on "flagged since" put page boundaries inside runs of equal keys.
    submit_scoring(client, "ST-E", 40)
    submit_scoring(client, "ST-A", 40)
    silence(client, "ST-S")
    run_worker(T0)
    submit_scoring(client, "ST-D", 40)
    submit_scoring(client, "ST-C", 40)
    submit_scoring(client, "ST-Z", 0)
    submit_scoring(client, "ST-B", 20)
    run_worker(T1)
    expected = ["ST-S", "ST-Z", "ST-B", "ST-A", "ST-E", "ST-C", "ST-D"]
    assert station_ids(poor_hygiene(client)) == expected

    pages = all_pages(client, limit=3)

    assert [station_ids(page) for page in pages] == [expected[0:3], expected[3:6], expected[6:]]
    assert [page["total"] for page in pages] == [7, 7, 7]
    assert all(page["scored_at"] == iso(T1) for page in pages)


def test_a_last_full_page_has_no_next_cursor(client: FlaskClient, run_worker: RunWorker) -> None:
    for station in ("ST-1", "ST-2", "ST-3", "ST-4"):
        submit_scoring(client, station, 30)
    run_worker(T0)

    pages = all_pages(client, limit=2)

    assert [station_ids(page) for page in pages] == [["ST-1", "ST-2"], ["ST-3", "ST-4"]]


def test_paging_keeps_the_filters(app: Flask, client: FlaskClient, run_worker: RunWorker) -> None:
    for station in ("ST-1", "ST-2", "ST-3", "ST-4", "ST-5"):
        submit_scoring(client, station, 30)
    for station in ("ST-2", "ST-3", "ST-5"):
        set_registry_facts(app, station, "eu-west", verified=True)
    run_worker(T0)

    pages = all_pages(client, region="eu-west", limit=2)

    assert [station_ids(page) for page in pages] == [["ST-2", "ST-3"], ["ST-5"]]
    assert [page["total"] for page in pages] == [3, 3]


def test_pages_hold_50_stations_by_default_and_at_most_500(
    client: FlaskClient, run_worker: RunWorker
) -> None:
    for number in range(51):
        silence(client, f"ST-{number:03}")
    run_worker(T0)

    first = poor_hygiene(client)
    assert len(first["items"]) == 50
    assert first["total"] == 51
    second = poor_hygiene(client, cursor=first["next_cursor"])
    assert station_ids(second) == ["ST-050"]
    assert second["next_cursor"] is None

    assert len(poor_hygiene(client, limit=500)["items"]) == 51
    for limit in (0, 501):
        response = client.get(
            "/poor-hygiene", query_string={"limit": limit}, headers=auth(READ_KEY)
        )
        assert response.status_code == 422, limit


def test_a_malformed_cursor_is_rejected(client: FlaskClient) -> None:
    response = client.get(
        "/poor-hygiene", query_string={"cursor": "not-a-cursor"}, headers=auth(READ_KEY)
    )

    assert response.status_code == 400
    assert response.json["message"] == "The cursor is not valid."


def test_sorts_by_flagged_since_oldest_or_newest_first(
    client: FlaskClient, run_worker: RunWorker
) -> None:
    submit_scoring(client, "ST-OLD-40", 40)
    submit_scoring(client, "ST-OLD-20", 20)
    run_worker(T0)
    submit_scoring(client, "ST-NEW-10", 10)
    run_worker(T1)

    oldest_first = poor_hygiene(client, sort="flagged_since")
    newest_first = poor_hygiene(client, sort="-flagged_since")

    # Equal "flagged since" falls back to the worst score.
    assert station_ids(oldest_first) == ["ST-OLD-20", "ST-OLD-40", "ST-NEW-10"]
    assert station_ids(newest_first) == ["ST-NEW-10", "ST-OLD-20", "ST-OLD-40"]


def test_cursor_paging_follows_the_chosen_sort(client: FlaskClient, run_worker: RunWorker) -> None:
    submit_scoring(client, "ST-A", 30)
    submit_scoring(client, "ST-B", 30)
    run_worker(T0)
    submit_scoring(client, "ST-C", 20)
    submit_scoring(client, "ST-D", 40)
    run_worker(T1)

    newest_first = all_pages(client, sort="-flagged_since", limit=1)
    oldest_first = all_pages(client, sort="flagged_since", limit=1)

    assert [station_ids(page) for page in newest_first] == [["ST-C"], ["ST-D"], ["ST-A"], ["ST-B"]]
    assert [station_ids(page) for page in oldest_first] == [["ST-A"], ["ST-B"], ["ST-C"], ["ST-D"]]


def test_a_cursor_from_another_sort_is_rejected(client: FlaskClient, run_worker: RunWorker) -> None:
    submit_scoring(client, "ST-A", 30)
    submit_scoring(client, "ST-B", 30)
    run_worker(T0)
    cursor = poor_hygiene(client, limit=1)["next_cursor"]

    response = client.get(
        "/poor-hygiene",
        query_string={"sort": "flagged_since", "cursor": cursor},
        headers=auth(READ_KEY),
    )

    assert response.status_code == 400


def test_the_list_needs_the_read_role(client: FlaskClient) -> None:
    assert client.get("/poor-hygiene").status_code == 401
    assert client.get("/poor-hygiene", headers=auth(INGEST_KEY)).status_code == 403


def test_before_any_scoring_run_the_list_is_empty(client: FlaskClient) -> None:
    submit_scoring(client, "ST-1", 30)

    assert poor_hygiene(client) == {"items": [], "total": 0, "next_cursor": None, "scored_at": None}
