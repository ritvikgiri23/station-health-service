"""The scoring run: the worker's "run once at `now`" entry point (ADR-0003).

Needs an app context. Reads every Health Report in the Scoring Window in one query,
assesses each registered Station through the scoring core against its current Station
health, upserts the Station health rows whose visible state changed, appends Flag Changes,
and records the run.
"""

import time
from collections import defaultdict
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from typing import Any

from sqlalchemy import Table, insert, select
from sqlalchemy.dialects.mysql import Insert
from sqlalchemy.dialects.mysql import insert as mysql_insert

from station_health.extensions import Base, db
from station_health.health.models import (
    SCORING_RUN_RECORD_ID,
    FlagChangeRecord,
    ScoringRunRecord,
    StationHealth,
)
from station_health.reports.models import ConnectivityStatus, HealthReport
from station_health.runtime import current_settings
from station_health.scoring import (
    NOT_FLAGGED,
    Assessment,
    FlagState,
    StationScore,
    WindowReport,
    assess_station,
)
from station_health.stations.models import Station

# The Station health columns whose change makes a scoring run write the row.
VISIBLE_STATE = ("hygiene_score", "silent", "poor_hygiene", "flag_reason", "firmware_version")


@dataclass(frozen=True)
class ScoringRun:
    scored_at: datetime
    stations_scored: int
    # Station health rows written: those whose visible state changed, or that were new.
    stations_written: int
    flag_changes: int
    duration_ms: float


def run_scoring_once(now: datetime) -> ScoringRun:
    """Assess every registered Station from its Scoring Window ending at `now`."""
    started = time.perf_counter()
    settings = current_settings()
    window, firmware = _window_reports(now - settings.scoring_window, now)
    current = _current_health()

    rows: list[dict[str, Any]] = []
    changes: list[dict[str, Any]] = []
    # Sorted, so the Flag Changes of one run are appended in a stable order.
    station_ids = sorted(db.session.scalars(select(Station.station_id)))
    for station_id in station_ids:
        previous = current.get(station_id)
        assessment = assess_station(
            window.get(station_id, []),
            _flag_state(previous) if previous else NOT_FLAGGED,
            now,
            settings.scoring,
        )
        # A Station with no Health Report in the window keeps its last known firmware.
        firmware_version = firmware.get(
            station_id, previous["firmware_version"] if previous else None
        )
        row = _health_row(station_id, assessment, firmware_version)
        if previous is None or any(row[c] != previous[c] for c in VISIBLE_STATE):
            rows.append(row)
        if assessment.flag_change is not None:
            changes.append(
                {
                    "station_id": station_id,
                    "changed_at": now,
                    "direction": assessment.flag_change.direction,
                    "flag_reason": assessment.flag_change.flag_reason,
                    "hygiene_score": row["hygiene_score"],
                }
            )
    if rows:
        db.session.execute(_upsert(StationHealth), rows)
    if changes:
        db.session.execute(insert(_table(FlagChangeRecord)), changes)

    run = ScoringRun(
        scored_at=now,
        stations_scored=len(station_ids),
        stations_written=len(rows),
        flag_changes=len(changes),
        duration_ms=round((time.perf_counter() - started) * 1000, 1),
    )
    db.session.execute(
        _upsert(ScoringRunRecord),
        {
            "id": SCORING_RUN_RECORD_ID,
            "scored_at": run.scored_at,
            "stations_scored": run.stations_scored,
            "duration_ms": run.duration_ms,
        },
    )
    db.session.commit()
    return run


def _current_health() -> dict[str, dict[str, Any]]:
    """Each Station's stored visible state and flag state, by `station_id`."""
    columns = [
        StationHealth.station_id,
        *(getattr(StationHealth, c) for c in VISIBLE_STATE),
        StationHealth.flagged_since,
    ]
    return {row["station_id"]: dict(row) for row in db.session.execute(select(*columns)).mappings()}


def _flag_state(health: dict[str, Any]) -> FlagState:
    return FlagState(
        poor_hygiene=health["poor_hygiene"],
        flag_reason=health["flag_reason"],
        flagged_since=health["flagged_since"],
    )


def _health_row(
    station_id: str, assessment: Assessment, firmware_version: str | None
) -> dict[str, Any]:
    score = assessment.score
    # A Silent Station has no score, so every part is null.
    parts = asdict(score) if score else dict.fromkeys(f.name for f in fields(StationScore))
    return {
        "station_id": station_id,
        **parts,
        "report_count": assessment.report_count,
        "silent": assessment.silent,
        "poor_hygiene": assessment.flag.poor_hygiene,
        "flag_reason": assessment.flag.flag_reason,
        "flagged_since": assessment.flag.flagged_since,
        "firmware_version": firmware_version,
    }


def _window_reports(
    start: datetime, end: datetime
) -> tuple[dict[str, list[WindowReport]], dict[str, str]]:
    """Health Reports with `timestamp` in (start, end], grouped by Station, and each
    Station's firmware version from the newest of them.
    """
    statement = select(
        HealthReport.station_id,
        HealthReport.timestamp,
        HealthReport.connectivity_status,
        HealthReport.latency_ms,
        HealthReport.error_count,
        HealthReport.firmware_version,
    ).where(HealthReport.timestamp > start, HealthReport.timestamp <= end)
    grouped: dict[str, list[WindowReport]] = defaultdict(list)
    newest: dict[str, tuple[datetime, str]] = {}
    for station_id, timestamp, status, latency_ms, error_count, firmware in db.session.execute(
        statement
    ):
        grouped[station_id].append(
            WindowReport(
                online=status is ConnectivityStatus.ONLINE,
                latency_ms=latency_ms,
                error_count=error_count,
            )
        )
        if station_id not in newest or timestamp > newest[station_id][0]:
            newest[station_id] = (timestamp, firmware)
    return grouped, {station_id: firmware for station_id, (_, firmware) in newest.items()}


def _upsert(model: type[Base]) -> Insert:
    """INSERT ... ON DUPLICATE KEY UPDATE of every non-key column.

    Built on the Core table: the ORM's bulk insert would leave out None values, so a row
    with no latency score could not overwrite an older one.
    """
    table = _table(model)
    statement = mysql_insert(table)
    return statement.on_duplicate_key_update(
        {c.name: statement.inserted[c.name] for c in table.columns if not c.primary_key}
    )


def _table(model: type[Base]) -> Table:
    table = model.__table__
    assert isinstance(table, Table)
    return table
