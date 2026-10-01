"""The metrics trend: one point per completed hour over the past N hours, overall and
optionally per Region, built from hourly summaries and never raw Health Reports.

A point covers the Stations that reported in that hour, since summaries exist only for
those: Silent and Poor Hygiene history is not kept, so a point counts the Stations whose
average Hygiene Score for the hour was below the Flag Threshold instead. A Station's
Region is its current one in the Station Registry; one no longer registered, or without
a Region, is `unassigned`.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import ColumnElement, Integer, cast, func, literal_column, select

from station_health.extensions import db
from station_health.metrics.snapshot import UNASSIGNED_REGION
from station_health.runtime import current_settings
from station_health.stations.models import Station
from station_health.summaries.models import HourlySummary
from station_health.summaries.summarise import HOUR, floor_hour

DEFAULT_TREND_HOURS = 24


class TrendGrouping(StrEnum):
    REGION = "region"


@dataclass(frozen=True)
class TrendPoint:
    hour: datetime
    reporting_station_count: int
    below_flag_threshold_count: int
    # Each None when no Station reported in the hour.
    average_hygiene_score: float | None
    average_availability: float | None
    average_p95_latency_ms: float | None


@dataclass(frozen=True)
class TrendGroup:
    key: str
    points: list[TrendPoint]


@dataclass(frozen=True)
class MetricsTrend:
    hours: int
    group_by: TrendGrouping | None
    # Oldest first, one for each of the `hours` completed hours before now.
    points: list[TrendPoint]
    # None without a grouping; ordered by key, with `unassigned` last.
    groups: list[TrendGroup] | None


def metrics_trend(now: datetime, hours: int, group_by: TrendGrouping | None) -> MetricsTrend:
    end = floor_hour(now)
    hour_starts = [end - (hours - n) * HOUR for n in range(hours)]
    in_range = (HourlySummary.hour_start >= hour_starts[0], HourlySummary.hour_start < end)
    overall = {row.hour_start: row for row in db.session.execute(_aggregate().where(*in_range))}

    groups = None
    if group_by is not None:
        by_region: dict[str | None, dict[datetime, Any]] = defaultdict(dict)
        statement = (
            _aggregate(Station.region.label("key"))
            .outerjoin(Station, Station.station_id == HourlySummary.station_id)
            .where(*in_range)
            .group_by(Station.region)
        )
        for row in db.session.execute(statement):
            by_region[row.key][row.hour_start] = row
        groups = [
            TrendGroup(key=key or UNASSIGNED_REGION, points=_series(hour_starts, rows))
            for key, rows in sorted(
                by_region.items(), key=lambda item: (item[0] is None, item[0] or "")
            )
        ]
    return MetricsTrend(
        hours=hours, group_by=group_by, points=_series(hour_starts, overall), groups=groups
    )


def _aggregate(*keys: ColumnElement[Any]) -> Any:
    flag_threshold = current_settings().scoring.flag_threshold
    below = HourlySummary.average_hygiene_score < flag_threshold
    return select(
        HourlySummary.hour_start,
        *keys,
        func.count().label("reporting_station_count"),
        func.sum(cast(below, Integer)).label("below_flag_threshold_count"),
        func.avg(HourlySummary.average_hygiene_score).label("average_hygiene_score"),
        # Adding 0E0 makes the division DOUBLE: MySQL's DECIMAL division keeps 4 places.
        func.avg(
            (HourlySummary.online_count + literal_column("0E0")) / HourlySummary.report_count
        ).label("average_availability"),
        func.avg(HourlySummary.p95_latency_ms).label("average_p95_latency_ms"),
    ).group_by(HourlySummary.hour_start)


def _series(hour_starts: list[datetime], rows: dict[datetime, Any]) -> list[TrendPoint]:
    """A point for every hour, empty where no Station reported."""
    return [_point(hour, rows.get(hour)) for hour in hour_starts]


def _point(hour: datetime, row: Any) -> TrendPoint:
    if row is None:
        return TrendPoint(hour, 0, 0, None, None, None)
    return TrendPoint(
        hour=hour,
        reporting_station_count=int(row.reporting_station_count),
        below_flag_threshold_count=int(row.below_flag_threshold_count),
        average_hygiene_score=_float(row.average_hygiene_score),
        average_availability=_float(row.average_availability),
        average_p95_latency_ms=_float(row.average_p95_latency_ms),
    )


def _float(value: Any) -> float | None:
    # MySQL's AVG of an integer expression is a DECIMAL.
    return None if value is None else float(value)
