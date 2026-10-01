"""Backfill mode: `flask backfill-reports` bulk-loads the past hours of Health Reports.

Needs an app context. Rather than going through HTTP, it calls ingest's own validation
(`HealthReportSchema`) and storage (`record_health_reports`), in batches, so a reviewer
gets a day of history in seconds. It writes no summaries: the worker's summary catch-up
summarises the backfilled hours on its next cycle, as it would after an outage.

The fleet, profiles and readings are the live simulator's, one Health Report per Station
per whole minute, so running it again stores nothing new, and the live simulator started
with the same fleet size carries on with the same Stations.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

import click
from flask.cli import with_appcontext
from marshmallow import ValidationError

from station_health.reports.ingest import record_health_reports
from station_health.reports.models import HealthReport
from station_health.reports.schemas import HealthReportSchema
from station_health.runtime import current_settings, current_time
from station_health.simulator.profiles import (
    SimStation,
    fleet,
    health_report,
    reading_generators,
)
from station_health.stations.registry import register_stations

logger = logging.getLogger("station_health.simulator")

MINUTE = timedelta(minutes=1)
BATCH_SIZE = 5000
REGISTER_BATCH_SIZE = 1000


class HoursBeyondRetention(ValueError):
    """Ingest rejects Health Reports older than raw retention, so backfill cannot go further."""


@dataclass(frozen=True)
class BackfillResult:
    stored: int
    duplicates: int
    rejected: int


def run_backfill(
    stations: Sequence[SimStation], hours: int, now: datetime, seed: int = 1
) -> BackfillResult:
    """Register the fleet's registered Stations, then store each Station's Health Report
    for every whole minute from `hours` before `now` up to `now`.

    Raises HoursBeyondRetention if `hours` exceeds raw retention. Each batch is received
    as of the clock, like a Health Report through ingest.
    """
    retention = current_settings().raw_retention
    if timedelta(hours=hours) > retention:
        raise HoursBeyondRetention(
            f"must not exceed raw retention ({retention.total_seconds() / 3600:g} hours)."
        )
    registered = [s for s in stations if s.region is not None]
    for start in range(0, len(registered), REGISTER_BATCH_SIZE):
        chunk = registered[start : start + REGISTER_BATCH_SIZE]
        register_stations({s.station_id: s.region for s in chunk}, now)
    rngs = reading_generators(stations, seed)

    schema = HealthReportSchema()
    first_timestamp = _ceil_minute(now - timedelta(hours=hours))
    minutes = int((now - first_timestamp) / MINUTE) + 1
    stored = submitted = rejected = 0
    batch: list[HealthReport] = []
    for minute in range(minutes):
        timestamp = first_timestamp + minute * MINUTE
        for station in stations:
            payload = health_report(station, minute, timestamp, rngs[station.station_id])
            if payload is None:
                continue
            try:
                batch.append(schema.load(payload))
            except ValidationError as error:
                rejected += 1
                logger.warning(
                    "Health Report not accepted",
                    extra={"station_id": station.station_id, "error": error.messages},
                )
            if len(batch) >= BATCH_SIZE:
                stored += record_health_reports(batch, current_time())
                submitted += len(batch)
                batch = []
    stored += record_health_reports(batch, current_time())
    submitted += len(batch)
    return BackfillResult(stored=stored, duplicates=submitted - stored, rejected=rejected)


def _ceil_minute(moment: datetime) -> datetime:
    floored = moment.replace(second=0, microsecond=0)
    return floored if floored == moment else floored + MINUTE


@click.command("backfill-reports")
@click.option(
    "--stations",
    type=click.IntRange(min=1),
    default=50,
    show_default=True,
    help="Stations to simulate, the same fleet as the live simulator's --stations.",
)
@click.option(
    "--hours",
    type=click.IntRange(min=1),
    default=24,
    show_default=True,
    help="Hours of history to load, at most raw retention.",
)
@click.option("--seed", type=int, default=1, show_default=True, help="Random seed for readings.")
@with_appcontext
def backfill_reports(stations: int, hours: int, seed: int) -> None:
    """Load the past hours of Health Reports for the simulator's fleet.

    The worker's next cycle builds their hourly summaries.
    """
    try:
        result = run_backfill(fleet(stations), hours, current_time(), seed)
    except HoursBeyondRetention as error:
        raise click.BadParameter(str(error), param_hint="--hours") from None
    click.echo(
        f"Stored {result.stored} Health Reports, {result.duplicates} duplicates ignored, "
        f"{result.rejected} rejected, for {stations} Stations over {hours} hours."
    )
