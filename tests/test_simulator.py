"""The simulator's live mode: it plays the Collector through the API, and each scenario
profile produces its expected outcome once the worker has scored a simulated window.
"""

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from flask.testing import FlaskClient

from station_health.simulator.live import run_live
from station_health.simulator.profiles import Profile, SimStation, fleet
from station_health.worker.scoring_run import ScoringRun
from tests.support import ADMIN_KEY, INGEST_KEY, READ_KEY, START, FakeClock, auth

RunWorker = Callable[[datetime], ScoringRun]


class FlaskClientApi:
    """The simulator's view of the API, served by the Flask test client."""

    def __init__(self, client: FlaskClient, clock: FakeClock) -> None:
        self.client = client
        self.clock = clock
        # (when it was sent, its timestamp) for every Health Report submitted.
        self.sent: list[tuple[datetime, datetime]] = []

    def register_station(self, station_id: str, region: str) -> None:
        response = self.client.put(
            f"/stations/{station_id}", json={"region": region}, headers=auth(ADMIN_KEY)
        )
        assert response.status_code in (200, 201), response.json

    def submit(self, reports: list[dict[str, Any]]) -> None:
        for report in reports:
            response = self.client.post("/health-reports", json=report, headers=auth(INGEST_KEY))
            assert response.status_code == 201, response.json
            self.sent.append((self.clock.now, datetime.fromisoformat(report["timestamp"])))


def fake_sleep(clock: FakeClock) -> Callable[[float], None]:
    def sleep(seconds: float) -> None:
        clock.now += timedelta(seconds=seconds)

    return sleep


def station_of(stations: list[SimStation], profile: Profile) -> str:
    return next(s.station_id for s in stations if s.profile is profile)


def hygiene(client: FlaskClient, station_id: str) -> Any:
    response = client.get(f"/stations/{station_id}/health", headers=auth(READ_KEY))
    assert response.status_code == 200, response.json
    return response.json["hygiene"]


def test_every_profile_is_in_a_fleet_of_ten() -> None:
    assert {s.profile for s in fleet(10)} == set(Profile)


def test_each_profile_yields_its_expected_outcome_after_a_simulated_window(
    client: FlaskClient, clock: FakeClock, run_worker: RunWorker
) -> None:
    stations = fleet(10)
    api = FlaskClientApi(client, clock)

    run_live(
        api,
        stations,
        speed=60,
        backlog=timedelta(minutes=30),
        clock=clock,
        sleep=fake_sleep(clock),
        stop_after_minutes=31,
    )
    # A full Scoring Window: the Health Reports of minutes 16 to 30, the last one at START.
    run_worker(clock.now)

    healthy = hygiene(client, station_of(stations, Profile.HEALTHY))
    assert healthy["poor_hygiene"] is False
    assert healthy["score"] >= 90
    for profile, reason in [
        (Profile.FLAPPING, "availability"),
        (Profile.SLOW, "latency"),
        (Profile.ERROR_PRONE, "errors"),
        (Profile.GOES_SILENT, "silent"),
    ]:
        body = hygiene(client, station_of(stations, profile))
        assert body["poor_hygiene"] is True, profile
        assert body["flag_reason"] == reason, profile
    assert hygiene(client, station_of(stations, Profile.GOES_SILENT))["silent"] is True

    unregistered = station_of(stations, Profile.UNREGISTERED)
    entry = client.get(f"/stations/{unregistered}", headers=auth(ADMIN_KEY))
    assert entry.status_code == 200
    assert entry.json["verified"] is False
    assert entry.json["region"] is None


def test_the_speed_multiplier_replays_the_backlog_quickly_then_keeps_real_time(
    client: FlaskClient, clock: FakeClock
) -> None:
    api = FlaskClientApi(client, clock)

    run_live(
        api,
        [SimStation("ST-000001", Profile.HEALTHY, region="us-west", firmware_version="1.4.2")],
        speed=60,
        backlog=timedelta(minutes=30),
        clock=clock,
        sleep=fake_sleep(clock),
        stop_after_minutes=35,
    )

    sent_at = [when for when, _ in api.sent]
    timestamps = [timestamp for _, timestamp in api.sent]
    # One Health Report per simulated minute, the first a backlog before the start.
    assert timestamps == [START - timedelta(minutes=30 - m) for m in range(35)]
    # At 60x, 30 simulated minutes take 30 seconds.
    assert sent_at[29] == START + timedelta(seconds=29)
    # Caught up, it sends each minute's Health Report as that minute arrives, never early.
    assert sent_at[34] == START + timedelta(minutes=4)
    assert all(timestamp <= when for when, timestamp in api.sent)


def test_health_reports_are_timestamped_on_whole_minutes_so_a_restart_replays_duplicates(
    client: FlaskClient, clock: FakeClock
) -> None:
    clock.now = START + timedelta(seconds=20)
    api = FlaskClientApi(client, clock)

    run_live(
        api,
        [SimStation("ST-000001", Profile.HEALTHY, region="us-west", firmware_version="1.4.2")],
        speed=60,
        backlog=timedelta(minutes=30),
        clock=clock,
        sleep=fake_sleep(clock),
        stop_after_minutes=3,
    )

    assert [timestamp for _, timestamp in api.sent] == [
        START - timedelta(minutes=30 - m) for m in range(3)
    ]
