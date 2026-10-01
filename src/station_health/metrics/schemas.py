from marshmallow import Schema, fields

from station_health.health.schemas import scored_at_field
from station_health.metrics.snapshot import UNASSIGNED_REGION, UNREPORTED_FIRMWARE, MetricsGrouping


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
