"""The scoring run: the worker's "run once at `now`" entry point (ADR-0003).

Needs an app context. Reads every Health Report in the Scoring Window in one query,
scores each Station through the scoring core, upserts Station health, and records the run.
"""

import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime

from sqlalchemy import Table, select
from sqlalchemy.dialects.mysql import Insert, insert

from station_health.extensions import Base, db
from station_health.health.models import SCORING_RUN_RECORD_ID, ScoringRunRecord, StationHealth
from station_health.reports.models import ConnectivityStatus, HealthReport
from station_health.runtime import current_settings
from station_health.scoring import WindowReport, score_station


@dataclass(frozen=True)
class ScoringRun:
    scored_at: datetime
    stations_scored: int
    duration_ms: float


def run_scoring_once(now: datetime) -> ScoringRun:
    """Score every Station with Health Reports in the Scoring Window ending at `now`."""
    started = time.perf_counter()
    settings = current_settings()

    rows = [
        {
            "station_id": station_id,
            **asdict(score_station(reports, settings.scoring)),
            "report_count": len(reports),
        }
        for station_id, reports in _window_reports(now - settings.scoring_window, now).items()
    ]
    if rows:
        db.session.execute(_upsert(StationHealth), rows)

    run = ScoringRun(
        scored_at=now,
        stations_scored=len(rows),
        duration_ms=round((time.perf_counter() - started) * 1000, 1),
    )
    db.session.execute(_upsert(ScoringRunRecord), {"id": SCORING_RUN_RECORD_ID, **asdict(run)})
    db.session.commit()
    return run


def _window_reports(start: datetime, end: datetime) -> dict[str, list[WindowReport]]:
    """Health Reports with `timestamp` in (start, end], grouped by Station."""
    statement = select(
        HealthReport.station_id,
        HealthReport.connectivity_status,
        HealthReport.latency_ms,
        HealthReport.error_count,
    ).where(HealthReport.timestamp > start, HealthReport.timestamp <= end)
    grouped: dict[str, list[WindowReport]] = defaultdict(list)
    for station_id, status, latency_ms, error_count in db.session.execute(statement):
        grouped[station_id].append(
            WindowReport(
                online=status is ConnectivityStatus.ONLINE,
                latency_ms=latency_ms,
                error_count=error_count,
            )
        )
    return grouped


def _upsert(model: type[Base]) -> Insert:
    """INSERT ... ON DUPLICATE KEY UPDATE of every non-key column.

    Built on the Core table: the ORM's bulk insert would leave out None values, so a row
    with no latency score could not overwrite an older one.
    """
    table = model.__table__
    assert isinstance(table, Table)
    statement = insert(table)
    return statement.on_duplicate_key_update(
        {c.name: statement.inserted[c.name] for c in table.columns if not c.primary_key}
    )
