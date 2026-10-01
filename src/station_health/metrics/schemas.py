from typing import Any

from marshmallow import Schema, ValidationError, fields, validates

from station_health.health.schemas import scored_at_field
from station_health.metrics.snapshot import UNASSIGNED_REGION, UNREPORTED_FIRMWARE, MetricsGrouping
from station_health.metrics.trend import DEFAULT_TREND_HOURS, TrendGrouping
from station_health.runtime import current_settings
from station_health.summaries.summarise import HOUR


class MetricsSnapshotQuerySchema(Schema):
    group_by = fields.Enum(
        MetricsGrouping,
        by_value=True,
        metadata={
            "description": f"Also break the snapshot down by Region (Stations without one as "
            f"`{UNASSIGNED_REGION}`) or by firmware version (Stations with none reported yet as "
            f"`{UNREPORTED_FIRMWARE}`)."
        },
    )


def _average(description: str) -> fields.Float:
    return fields.Float(
        required=True,
        allow_none=True,
        metadata={
            "description": f"{description}, over the Stations that have a score, so Silent "
            "and not yet scored ones are left out. Null when none has a score."
        },
    )


class MetricsFiguresSchema(Schema):
    station_count = fields.Integer(
        required=True, metadata={"description": "Stations in the Station Registry."}
    )
    poor_hygiene_count = fields.Integer(required=True)
    poor_hygiene_percentage = fields.Float(
        required=True,
        allow_none=True,
        metadata={"description": "Of the station count, 0-100. Null when there are no Stations."},
    )
    silent_count = fields.Integer(required=True)
    unverified_count = fields.Integer(
        required=True, metadata={"description": "Unverified Stations."}
    )
    average_hygiene_score = _average("Mean Hygiene Score, 0-100")
    average_availability = _average("Mean Availability, 0-1")
    average_p95_latency_ms = _average("Mean p95 latency of online Health Reports")


class MetricsGroupSchema(MetricsFiguresSchema):
    key = fields.String(
        required=True,
        metadata={
            "description": f"The Region or firmware version: `{UNASSIGNED_REGION}` for "
            f"Stations without a Region, `{UNREPORTED_FIRMWARE}` for those with no firmware "
            "version reported yet."
        },
    )


class MetricsSnapshotSchema(Schema):
    overall = fields.Nested(MetricsFiguresSchema, required=True)
    group_by = fields.Enum(MetricsGrouping, by_value=True, required=True, allow_none=True)
    groups = fields.List(
        fields.Nested(MetricsGroupSchema),
        required=True,
        allow_none=True,
        metadata={
            "description": "One per Region or firmware version, ordered by key with "
            f"`{UNASSIGNED_REGION}` / `{UNREPORTED_FIRMWARE}` last. Null without `group_by`."
        },
    )
    scored_at = scored_at_field()


def _trend_average(description: str) -> fields.Float:
    return fields.Float(
        required=True,
        allow_none=True,
        metadata={"description": f"{description}. Null when no Station reported in the hour."},
    )


class MetricsTrendQuerySchema(Schema):
    hours = fields.Integer(
        load_default=DEFAULT_TREND_HOURS,
        metadata={
            "description": "How many completed hours before now, from 1 up to the summary "
            f"retention (SUMMARY_RETENTION_DAYS x 24). Default {DEFAULT_TREND_HOURS}."
        },
    )
    group_by = fields.Enum(
        TrendGrouping,
        by_value=True,
        metadata={
            "description": "Also break the trend down by Region (Stations without one, or no "
            f"longer registered, as `{UNASSIGNED_REGION}`)."
        },
    )

    @validates("hours")
    def _within_summary_retention(self, value: int, **_: Any) -> None:
        limit = current_settings().summary_retention // HOUR
        if not 1 <= value <= limit:
            raise ValidationError(f"Must be from 1 to {limit}, the summary retention in hours.")


class TrendPointSchema(Schema):
    hour = fields.AwareDateTime(
        required=True, metadata={"description": "Start of the hour, [hour, hour + 1h)."}
    )
    reporting_station_count = fields.Integer(
        required=True,
        metadata={"description": "Stations with Health Reports in the hour (with a summary)."},
    )
    below_flag_threshold_count = fields.Integer(
        required=True,
        metadata={
            "description": "Reporting Stations whose average Hygiene Score for the hour was "
            "below the Flag Threshold."
        },
    )
    average_hygiene_score = _trend_average(
        "Mean of the Stations' average Hygiene Scores for the hour, 0-100"
    )
    average_availability = _trend_average(
        "Mean of the Stations' Availability over the hour: their share of the hour's "
        "Health Reports that were not Offline, 0-1"
    )
    average_p95_latency_ms = _trend_average(
        "Mean of the Stations' p95 latency of online Health Reports; Stations with none "
        "online are left out"
    )


class TrendGroupSchema(Schema):
    key = fields.String(
        required=True,
        metadata={
            "description": f"The Region, or `{UNASSIGNED_REGION}` for Stations without one or "
            "no longer registered."
        },
    )
    points = fields.List(fields.Nested(TrendPointSchema), required=True)


class MetricsTrendSchema(Schema):
    hours = fields.Integer(required=True)
    group_by = fields.Enum(TrendGrouping, by_value=True, required=True, allow_none=True)
    points = fields.List(
        fields.Nested(TrendPointSchema),
        required=True,
        metadata={"description": "One per completed hour, oldest first."},
    )
    groups = fields.List(
        fields.Nested(TrendGroupSchema),
        required=True,
        allow_none=True,
        metadata={
            "description": "One per Region, each with a point for every hour, ordered by key "
            f"with `{UNASSIGNED_REGION}` last. Null without `group_by`."
        },
    )
