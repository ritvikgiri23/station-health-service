"""A Station's latest health status: registry facts, latest Health Report and Hygiene Score."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select

from station_health.extensions import db
from station_health.health.models import SCORING_RUN_RECORD_ID, ScoringRunRecord, StationHealth
from station_health.reports.models import HealthReport
from station_health.stations.models import Station
from station_health.stations.registry import find_station


@dataclass(frozen=True)
class StationHealthStatus:
    station: Station
    # By newest `timestamp`, not arrival order, so a late older Health Report never replaces it.
    latest_report: HealthReport | None
    # None until a scoring run has scored the Station.
    hygiene: StationHealth | None
    # When the last scoring run completed; None before the first one.
    scored_at: datetime | None


def station_health_status(station_id: str) -> StationHealthStatus | None:
    station = find_station(station_id)
    if station is None:
        return None
    latest_report = db.session.scalar(
        select(HealthReport)
        .where(HealthReport.station_id == station_id)
        .order_by(HealthReport.timestamp.desc())
        .limit(1)
    )
    run = db.session.get(ScoringRunRecord, SCORING_RUN_RECORD_ID)
    return StationHealthStatus(
        station=station,
        latest_report=latest_report,
        hygiene=db.session.get(StationHealth, station_id),
        scored_at=run.scored_at if run else None,
    )
