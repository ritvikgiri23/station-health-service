"""The metrics snapshot: current fleet health overall, by Region or by firmware version.

Aggregated from the Station Registry and Station health, never from raw Health Reports,
so it reads one row per Station however many Health Reports there are. Every registered
Station counts; one not yet scored adds to no count but the station count, and the
averages are over the Stations that have a score, so Silent ones are left out of them.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import ColumnElement, Integer, cast, func, select

from station_health.extensions import db
from station_health.health.models import StationHealth
from station_health.health.status import last_scored_at
from station_health.stations.models import Station


class MetricsGrouping(StrEnum):
    REGION = "region"
    FIRMWARE_VERSION = "firmware_version"


# The group key of Stations with no Region, or whose firmware version no Health Report
# has given yet.
UNASSIGNED_REGION = "unassigned"
UNREPORTED_FIRMWARE = "unreported"

_GROUP_KEYS: dict[MetricsGrouping, tuple[ColumnElement[Any], str]] = {
    MetricsGrouping.REGION: (Station.region.expression, UNASSIGNED_REGION),
    MetricsGrouping.FIRMWARE_VERSION: (
        StationHealth.firmware_version.expression,
        UNREPORTED_FIRMWARE,
    ),
}


@dataclass(frozen=True)
class MetricsFigures:
    station_count: int
    poor_hygiene_count: int
    # Of the station count, 0-100; None when there are no Stations.
    poor_hygiene_percentage: float | None
    silent_count: int
    unverified_count: int
    # Each None when no Station in the group has a score.
    average_hygiene_score: float | None
    average_availability: float | None
    average_p95_latency_ms: float | None


@dataclass(frozen=True)
class MetricsGroup(MetricsFigures):
    key: str


@dataclass(frozen=True)
class MetricsSnapshot:
    overall: MetricsFigures
    group_by: MetricsGrouping | None
    # None without a grouping; ordered by key, with the unassigned/unreported group last.
    groups: list[MetricsGroup] | None
    # When the last scoring run completed; None before the first one.
    scored_at: datetime | None


def metrics_snapshot(group_by: MetricsGrouping | None = None) -> MetricsSnapshot:
    (overall,) = db.session.execute(_aggregate())
    groups = None
    if group_by is not None:
        key, fallback_key = _GROUP_KEYS[group_by]
        rows = db.session.execute(_aggregate(key.label("key")).group_by(key))
        groups = [
            MetricsGroup(key=row.key or fallback_key, **_figures(row))
            for row in sorted(rows, key=lambda row: (row.key is None, row.key or ""))
        ]
    return MetricsSnapshot(
        overall=MetricsFigures(**_figures(overall)),
        group_by=group_by,
        groups=groups,
        scored_at=last_scored_at(),
    )


def _aggregate(*keys: ColumnElement[Any]) -> Any:
    def total(condition: ColumnElement[bool]) -> ColumnElement[int]:
        return func.coalesce(func.sum(cast(condition, Integer)), 0)

    return select(
        *keys,
        func.count().label("station_count"),
        total(StationHealth.poor_hygiene.is_(True)).label("poor_hygiene_count"),
        total(StationHealth.silent.is_(True)).label("silent_count"),
        total(Station.verified.is_(False)).label("unverified_count"),
        func.avg(StationHealth.hygiene_score).label("average_hygiene_score"),
        func.avg(StationHealth.availability).label("average_availability"),
        func.avg(StationHealth.p95_latency_ms).label("average_p95_latency_ms"),
    ).outerjoin(StationHealth, StationHealth.station_id == Station.station_id)


def _figures(row: Any) -> dict[str, Any]:
    stations, poor = int(row.station_count), int(row.poor_hygiene_count)
    return {
        "station_count": stations,
        "poor_hygiene_count": poor,
        "poor_hygiene_percentage": 100 * poor / stations if stations else None,
        "silent_count": int(row.silent_count),
        "unverified_count": int(row.unverified_count),
        "average_hygiene_score": _float(row.average_hygiene_score),
        "average_availability": _float(row.average_availability),
        "average_p95_latency_ms": _float(row.average_p95_latency_ms),
    }


def _float(value: Any) -> float | None:
    # MySQL's AVG of an integer column is a DECIMAL.
    return None if value is None else float(value)
