"""The Health Report payload: validation shared by the ingest endpoint and the backfill."""

from datetime import UTC, datetime, timedelta
from typing import Any

from marshmallow import Schema, ValidationError, fields, post_load, validates
from marshmallow.validate import Length, Range

from station_health.reports.models import ERROR_COUNT_MAX, ConnectivityStatus, HealthReport
from station_health.runtime import current_settings, current_time


class StrictFloat(fields.Float):
    """A JSON number. Unlike `fields.Float`, numeric strings such as "12.5" are rejected."""

    def _validated(self, value: Any) -> float:
        if isinstance(value, str):
            raise self.make_error("invalid", input=value)
        return super()._validated(value)


class HealthReportSchema(Schema):
    station_id = fields.String(required=True, validate=Length(min=1, max=64))
    timestamp = fields.AwareDateTime(
        required=True,
        metadata={
            "description": "ISO 8601 with a timezone offset. Stored and returned in UTC. "
            "Rejected if too far in the future (INGEST_FUTURE_TOLERANCE_SECONDS, default "
            "5 minutes) or older than raw retention (RAW_RETENTION_HOURS, default 48 hours)."
        },
    )
    connectivity_status = fields.Enum(ConnectivityStatus, by_value=True, required=True)
    latency_ms = StrictFloat(required=True, validate=Range(min=0))
    error_count = fields.Integer(
        required=True,
        strict=True,
        validate=Range(min=0, max=ERROR_COUNT_MAX),
        metadata={"description": "Errors since the Station's previous Health Report."},
    )
    firmware_version = fields.String(required=True, validate=Length(min=1, max=64))

    @validates("timestamp")
    def _within_accepted_window(self, value: datetime, **_: Any) -> None:
        settings = current_settings()
        check_timestamp_window(
            value, current_time(), settings.ingest_future_tolerance, settings.raw_retention
        )

    @post_load
    def _to_health_report(self, data: dict[str, Any], **_: Any) -> HealthReport:
        data["timestamp"] = data["timestamp"].astimezone(UTC)
        return HealthReport(**data)


def check_timestamp_window(
    timestamp: datetime, now: datetime, future_tolerance: timedelta, raw_retention: timedelta
) -> None:
    if timestamp > now + future_tolerance:
        raise ValidationError(
            f"Timestamp is more than {_describe(future_tolerance)} in the future."
        )
    if timestamp < now - raw_retention:
        raise ValidationError(
            f"Timestamp is older than the raw retention period of {_describe(raw_retention)}."
        )


def _describe(span: timedelta) -> str:
    seconds = int(span.total_seconds())
    if seconds % 3600 == 0:
        return f"{seconds // 3600} hours"
    if seconds % 60 == 0:
        return f"{seconds // 60} minutes"
    return f"{seconds} seconds"
