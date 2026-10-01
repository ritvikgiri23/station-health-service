"""Scenario profiles: how each simulated Station behaves, so every scoring rule shows up.

Pure: no Flask, no HTTP. With the default scoring configuration, a full Scoring Window of
each profile yields:

- healthy: fast, online, almost no errors. Not flagged.
- flapping: Offline every other minute. Availability about 0.5, score about 50, Flag
  Reason `availability`.
- slow: p95 latency over 1000 ms, so a latency score of 0. Latency alone can cost at most
  40 points (its weight), leaving 60, which is not below the Flag Threshold, so it also
  has an error every other minute: score about 50, Flag Reason `latency`.
- error-prone: fast, but 3 to 5 errors per Health Report, so an error score of 0. Score
  40, Flag Reason `errors`.
- goes Silent: healthy for its first GOES_SILENT_AFTER simulated minutes, then sends
  nothing, so it is Silent once those Health Reports leave its window.
- unregistered: healthy, but never put in the Station Registry, so its first Health
  Report registers it as an Unverified Station.
"""

import random
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from station_health.stations.seed import seed_region, seed_station_id

GOES_SILENT_AFTER = 10
FIRMWARE_VERSIONS = ("1.4.2", "1.5.0", "2.0.1")


class Profile(StrEnum):
    HEALTHY = "healthy"
    FLAPPING = "flapping"
    SLOW = "slow"
    ERROR_PRONE = "error-prone"
    GOES_SILENT = "goes-silent"
    UNREGISTERED = "unregistered"


# Profiles are assigned to the fleet in this repeating order: half healthy, a tenth each.
PROFILE_MIX = (
    Profile.HEALTHY,
    Profile.FLAPPING,
    Profile.SLOW,
    Profile.ERROR_PRONE,
    Profile.GOES_SILENT,
    Profile.UNREGISTERED,
    Profile.HEALTHY,
    Profile.HEALTHY,
    Profile.HEALTHY,
    Profile.HEALTHY,
)


@dataclass(frozen=True)
class SimStation:
    station_id: str
    profile: Profile
    # None for an unregistered Station: the simulator never registers it.
    region: str | None
    firmware_version: str


def fleet(count: int) -> list[SimStation]:
    """`count` Stations with profiles assigned in PROFILE_MIX order.

    Registered Stations get the seed's IDs and Regions (ST-000001, ...), so the simulator
    and `flask seed-stations` describe the same Stations. Unregistered ones are numbered
    on their own (ST-UNREG-0001, ...), so no seeded Station shares their ID.
    """
    stations = []
    registered = unregistered = 0
    for index in range(count):
        profile = PROFILE_MIX[index % len(PROFILE_MIX)]
        firmware_version = FIRMWARE_VERSIONS[index % len(FIRMWARE_VERSIONS)]
        if profile is Profile.UNREGISTERED:
            unregistered += 1
            stations.append(
                SimStation(f"ST-UNREG-{unregistered:04d}", profile, None, firmware_version)
            )
        else:
            registered += 1
            stations.append(
                SimStation(
                    seed_station_id(registered), profile, seed_region(registered), firmware_version
                )
            )
    return stations


def health_report(
    station: SimStation, minute: int, timestamp: datetime, rng: random.Random
) -> dict[str, Any] | None:
    """The Health Report payload `station` sends for simulated `minute`, or None if it
    sends nothing that minute.
    """
    profile = station.profile
    if profile is Profile.GOES_SILENT and minute >= GOES_SILENT_AFTER:
        return None
    online = not (profile is Profile.FLAPPING and minute % 2 == 1)
    if not online:
        # The Station did not answer the Probe, so nothing was measured.
        latency_ms, error_count = 0.0, 0
    elif profile is Profile.SLOW:
        latency_ms = rng.uniform(1100, 1500)
        error_count = minute % 2
    elif profile is Profile.ERROR_PRONE:
        latency_ms = rng.uniform(40, 140)
        error_count = rng.randint(3, 5)
    else:
        latency_ms = rng.uniform(40, 140)
        error_count = 1 if rng.random() < 0.05 else 0
    return {
        "station_id": station.station_id,
        "timestamp": timestamp.isoformat(),
        "connectivity_status": "online" if online else "offline",
        "latency_ms": round(latency_ms, 1),
        "error_count": error_count,
        "firmware_version": station.firmware_version,
    }
