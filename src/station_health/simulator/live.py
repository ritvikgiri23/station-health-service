"""Live mode: send one Health Report per Station per simulated minute through the API.

Ingest rejects Health Reports from the future, so simulated time can never run ahead of
the clock. Instead it starts `backlog` in the past and runs `speed` times faster than real
time until it catches up, then keeps pace with the clock. A 30-minute backlog at 60x
fills the Scoring Window in 30 seconds and leaves a goes-Silent Station already Silent.

Timestamps fall on whole minutes, so a restarted simulator resends Health Reports the
service already has, which ingest ignores as duplicates, rather than doubling them up.
"""

import http.client
import json
import logging
import random
import threading
import urllib.request
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any, Protocol

from station_health.clock import Clock
from station_health.simulator.profiles import SimStation, health_report

logger = logging.getLogger("station_health.simulator")

MINUTE = timedelta(minutes=1)


class Api(Protocol):
    """What the simulator needs from the Station Health Service."""

    def register_station(self, station_id: str, region: str) -> None: ...

    def submit(self, reports: list[dict[str, Any]]) -> None: ...


def run_live(
    api: Api,
    stations: Sequence[SimStation],
    *,
    speed: float,
    backlog: timedelta,
    clock: Clock,
    sleep: Callable[[float], Any],
    stop_after_minutes: int | None = None,
    stop: threading.Event | None = None,
    seed: int = 1,
) -> None:
    """Register the fleet's registered Stations, then send each simulated minute's Health
    Reports until `stop_after_minutes` have been sent (forever if None) or `stop` is set.

    `speed` must be above 1, or simulated time never catches up with the clock.
    """
    if speed <= 1:
        raise ValueError("speed must be greater than 1")
    for station in stations:
        if station.region is not None:
            api.register_station(station.station_id, station.region)
    # One generator per Station, so a Station's readings do not depend on the fleet size.
    rngs = {s.station_id: random.Random(f"{seed}:{s.station_id}") for s in stations}

    real_start = clock()
    simulated_start = real_start.replace(second=0, microsecond=0) - backlog
    minute = 0
    while stop_after_minutes is None or minute < stop_after_minutes:
        timestamp = simulated_start + minute * MINUTE
        due = max(real_start + timedelta(minutes=minute / speed), timestamp)
        wait = (due - clock()).total_seconds()
        if wait > 0:
            sleep(wait)
        if stop is not None and stop.is_set():
            return
        reports = [
            report
            for station in stations
            if (report := health_report(station, minute, timestamp, rngs[station.station_id]))
        ]
        api.submit(reports)
        logger.info(
            "simulated minute",
            extra={"minute": minute, "timestamp": timestamp.isoformat(), "reports": len(reports)},
        )
        minute += 1


class HttpApi:
    """The Station Health Service over HTTP: admin key to register, ingest key to submit."""

    def __init__(
        self, base_url: str, ingest_key: str, admin_key: str, concurrency: int = 8
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.ingest_key = ingest_key
        self.admin_key = admin_key
        self.pool = ThreadPoolExecutor(max_workers=concurrency)

    def register_station(self, station_id: str, region: str) -> None:
        # A failure here is fatal: the scenarios rely on their Stations being registered.
        self._request("PUT", f"/stations/{station_id}", {"region": region}, self.admin_key)

    def submit(self, reports: list[dict[str, Any]]) -> None:
        """Send the Health Reports concurrently. A failed one is logged and not retried:
        a real Collector's lost Health Report is lost too.
        """
        failures = sum(not ok for ok in self.pool.map(self._submit_one, reports))
        if failures:
            logger.warning("Health Reports not accepted", extra={"failed": failures})

    def _submit_one(self, report: dict[str, Any]) -> bool:
        try:
            self._request("POST", "/health-reports", report, self.ingest_key)
        # OSError covers URLError (including HTTP error statuses), timeouts and resets.
        except (OSError, http.client.HTTPException) as error:
            logger.warning(
                "Health Report not accepted",
                extra={"station_id": report["station_id"], "error": str(error)},
            )
            return False
        return True

    def _request(self, method: str, path: str, body: dict[str, Any], key: str) -> None:
        request = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(body).encode(),
            method=method,
            headers={"Content-Type": "application/json", "X-API-Key": key},
        )
        # urlopen raises HTTPError, a URLError, for any status of 400 or more.
        with urllib.request.urlopen(request, timeout=10):
            pass
