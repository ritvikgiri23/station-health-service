"""Hourly summary catch-up: summarise every completed hour within raw retention that has
no summary yet (ADR-0001, ADR-0003).

Needs an app context. Because it looks for missing hours rather than "the hour that just
ended", it catches up by itself after the worker has been down, and summarises backfilled
history. An hour is summarised SUMMARY_DELAY after it ends, and counts as summarised once
it has any summary row, so Health Reports that arrive for it later are not added. Only
hours wholly within raw retention are considered: an older one may have lost Health
Reports to retention already. Each hour is committed on its own, so a long catch-up keeps
the hours it finished.
"""

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from sqlalchemy import insert, select

from station_health.extensions import db
from station_health.reports.models import ConnectivityStatus, HealthReport
from station_health.runtime import current_settings
from station_health.scoring import WindowReport
from station_health.summaries.models import HourlySummary
from station_health.summaries.summarise import HOUR, TimedReport, floor_hour, summarise_hour

# How long after an hour ends before it is summarised, so Health Reports from its last
# Probes are stored first. Ingest accepts Health Reports up to raw retention old, so any
# arriving later still miss their hour's summary.
SUMMARY_DELAY = timedelta(minutes=5)


@dataclass(frozen=True)
class SummaryCatchUp:
    hours_summarised: int
    summaries_written: int


def run_summary_catch_up(now: datetime) -> SummaryCatchUp:
    settings = current_settings()
    latest = floor_hour(now - SUMMARY_DELAY) - HOUR
    earliest = floor_hour(now - settings.raw_retention)
    if earliest < now - settings.raw_retention:
        earliest += HOUR
    summarised = set(
        db.session.scalars(
            select(HourlySummary.hour_start).distinct().where(HourlySummary.hour_start >= earliest)
        )
    )
    hours = written = 0
    hour_start = earliest
    while hour_start <= latest:
        if hour_start not in summarised:
            rows = _summaries(hour_start)
            if rows:
                db.session.execute(insert(HourlySummary), rows)
                db.session.commit()
                hours += 1
                written += len(rows)
        hour_start += HOUR
    db.session.commit()
    return SummaryCatchUp(hours_summarised=hours, summaries_written=written)


def _summaries(hour_start: datetime) -> list[dict[str, object]]:
    """One summary row per Station with Health Reports timestamped in the hour."""
    settings = current_settings()
    statement = select(
        HealthReport.station_id,
        HealthReport.timestamp,
        HealthReport.connectivity_status,
        HealthReport.latency_ms,
        HealthReport.error_count,
    ).where(HealthReport.timestamp >= hour_start, HealthReport.timestamp < hour_start + HOUR)
    by_station: dict[str, list[TimedReport]] = defaultdict(list)
    for station_id, timestamp, status, latency_ms, error_count in db.session.execute(statement):
        by_station[station_id].append(
            TimedReport(
                timestamp=timestamp,
                report=WindowReport(
                    online=status is ConnectivityStatus.ONLINE,
                    latency_ms=latency_ms,
                    error_count=error_count,
                ),
            )
        )
    return [
        {
            "hour_start": hour_start,
            "station_id": station_id,
            **asdict(
                summarise_hour(reports, hour_start, settings.scoring_window, settings.scoring)
            ),
        }
        for station_id, reports in sorted(by_station.items())
    ]
