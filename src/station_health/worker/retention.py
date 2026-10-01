"""Retention clean-up: delete raw Health Reports older than raw retention and hourly
summaries older than summary retention (ADR-0001).

Needs an app context. Deletes in batches of RETENTION_BATCH_SIZE rows, each committed on
its own, so no single statement holds locks for long or builds a huge undo log. In
production the tables would be partitioned by day and old partitions dropped instead.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import cast

from sqlalchemy import ColumnElement, CursorResult, delete

from station_health.extensions import Base, db
from station_health.reports.models import HealthReport
from station_health.runtime import current_settings
from station_health.summaries.models import HourlySummary
from station_health.summaries.summarise import floor_hour


@dataclass(frozen=True)
class Retention:
    reports_deleted: int
    summaries_deleted: int


def run_retention(now: datetime) -> Retention:
    settings = current_settings()
    return Retention(
        # The same cut-off ingest applies, so nothing ingest accepts is deleted.
        reports_deleted=_delete_in_batches(
            HealthReport,
            HealthReport.timestamp < now - settings.raw_retention,
            settings.retention_batch_size,
        ),
        summaries_deleted=_delete_in_batches(
            HourlySummary,
            # Whole hours, so the trend's oldest allowed hour is always still there.
            HourlySummary.hour_start < floor_hour(now) - settings.summary_retention,
            settings.retention_batch_size,
        ),
    )


def _delete_in_batches(model: type[Base], condition: ColumnElement[bool], batch_size: int) -> int:
    deleted = 0
    while True:
        result = cast(
            CursorResult[()],
            db.session.execute(
                delete(model).where(condition).with_dialect_options(mysql_limit=batch_size)
            ),
        )
        db.session.commit()
        deleted += result.rowcount
        if result.rowcount < batch_size:
            return deleted
