"""Storing Health Reports: shared by the ingest endpoint and the backfill."""

from collections.abc import Callable
from datetime import datetime

from pymysql.constants.ER import DUP_ENTRY, LOCK_DEADLOCK
from sqlalchemy import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError, OperationalError

from station_health.extensions import db
from station_health.reports.models import HealthReport
from station_health.stations.registry import register_unverified_stations

# Concurrent first Health Reports for a new Station can deadlock on its registration.
# MySQL rolls one back; retrying it is safe because the whole write is idempotent.
DEADLOCK_ATTEMPTS = 3


def record_health_report(report: HealthReport, received_at: datetime) -> tuple[HealthReport, bool]:
    """Store a validated Health Report, registering its Station as Unverified if it is new.

    Idempotent on (`station_id`, `timestamp`): if that Health Report is already stored,
    nothing is written and the stored one is returned. Returns (stored report, created).
    """
    report.received_at = received_at
    return _retrying_deadlocks(lambda: _insert(report, received_at))


def record_health_reports(reports: list[HealthReport], received_at: datetime) -> int:
    """Store a batch of validated Health Reports in one statement, registering new
    Stations as Unverified. Commits.

    Idempotent like `record_health_report`: a Health Report already stored, or repeated
    within the batch, is skipped. Returns how many were stored.
    """
    if not reports:
        return 0
    return _retrying_deadlocks(lambda: _insert_many(reports, received_at))


def _retrying_deadlocks[T](write: Callable[[], T]) -> T:
    for attempt in range(1, DEADLOCK_ATTEMPTS + 1):
        try:
            return write()
        except OperationalError as error:
            db.session.rollback()
            if _mysql_error_code(error) != LOCK_DEADLOCK or attempt == DEADLOCK_ATTEMPTS:
                raise
    raise AssertionError("unreachable")  # pragma: no cover


def _insert_many(reports: list[HealthReport], received_at: datetime) -> int:
    register_unverified_stations({r.station_id for r in reports}, received_at)
    rows = [
        {
            "station_id": r.station_id,
            "timestamp": r.timestamp,
            "connectivity_status": r.connectivity_status,
            "latency_ms": r.latency_ms,
            "error_count": r.error_count,
            "firmware_version": r.firmware_version,
            "received_at": received_at,
        }
        for r in reports
    ]
    # IGNORE also turns out-of-range values into warnings, but the rows have passed
    # validation, so the only thing it skips is a duplicate primary key.
    result = db.session.connection().execute(insert(HealthReport).prefix_with("IGNORE"), rows)
    assert isinstance(result, CursorResult)
    db.session.commit()
    return result.rowcount


def _insert(report: HealthReport, received_at: datetime) -> tuple[HealthReport, bool]:
    try:
        register_unverified_stations({report.station_id}, received_at)
        db.session.add(report)
        db.session.commit()
    except IntegrityError as error:
        db.session.rollback()
        if _mysql_error_code(error) != DUP_ENTRY:
            raise
        stored = db.session.get(HealthReport, (report.station_id, report.timestamp))
        if stored is None:  # pragma: no cover - only if deleted between the two statements
            raise
        return stored, False
    return report, True


def _mysql_error_code(error: IntegrityError | OperationalError) -> int | None:
    if error.orig is None or not error.orig.args:
        return None
    code = error.orig.args[0]
    return code if isinstance(code, int) else None
