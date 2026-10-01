"""Storing Health Reports: shared by the ingest endpoint and the backfill."""

from datetime import datetime

from pymysql.constants.ER import DUP_ENTRY, LOCK_DEADLOCK
from sqlalchemy.exc import IntegrityError, OperationalError

from station_health.extensions import db
from station_health.reports.models import HealthReport
from station_health.stations.registry import register_unverified_station

# Concurrent first Health Reports for a new Station can deadlock on its registration.
# MySQL rolls one back; retrying it is safe because the whole write is idempotent.
DEADLOCK_ATTEMPTS = 3


def record_health_report(report: HealthReport, received_at: datetime) -> tuple[HealthReport, bool]:
    """Store a validated Health Report, registering its Station as Unverified if it is new.

    Idempotent on (`station_id`, `timestamp`): if that Health Report is already stored,
    nothing is written and the stored one is returned. Returns (stored report, created).
    """
    report.received_at = received_at
    for attempt in range(1, DEADLOCK_ATTEMPTS + 1):
        try:
            return _insert(report, received_at)
        except OperationalError as error:
            db.session.rollback()
            if _mysql_error_code(error) != LOCK_DEADLOCK or attempt == DEADLOCK_ATTEMPTS:
                raise
    raise AssertionError("unreachable")  # pragma: no cover


def _insert(report: HealthReport, received_at: datetime) -> tuple[HealthReport, bool]:
    try:
        register_unverified_station(report.station_id, received_at)
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
