from marshmallow import Schema, fields

from station_health.reports.models import ConnectivityStatus


class LatestHealthReportSchema(Schema):
    timestamp = fields.AwareDateTime(required=True)
    connectivity_status = fields.Enum(ConnectivityStatus, by_value=True, required=True)
    latency_ms = fields.Float(required=True)
    error_count = fields.Integer(required=True)
    firmware_version = fields.String(required=True)


class HygieneSchema(Schema):
    score = fields.Integer(
        required=True,
        attribute="hygiene_score",
        metadata={"description": "Hygiene Score, 0-100: Availability x weighted quality x 100."},
    )
    availability = fields.Float(
        required=True,
        metadata={"description": "Share of Health Reports in the Scoring Window not Offline, 0-1."},
    )
    latency_score = fields.Float(
        required=True,
        allow_none=True,
        metadata={
            "description": "0-1, from the p95 latency of online Health Reports. "
            "Null when the window held no online Health Reports."
        },
    )
    error_score = fields.Float(
        required=True,
        allow_none=True,
        metadata={
            "description": "0-1, from errors per online Health Report. "
            "Null when the window held no online Health Reports."
        },
    )
    p95_latency_ms = fields.Float(required=True, allow_none=True)
    report_count = fields.Integer(
        required=True, metadata={"description": "Health Reports in the Scoring Window."}
    )


class StationHealthStatusSchema(Schema):
    station_id = fields.String(required=True, attribute="station.station_id")
    region = fields.String(required=True, allow_none=True, attribute="station.region")
    verified = fields.Boolean(
        required=True,
        attribute="station.verified",
        metadata={"description": "False for an Unverified Station."},
    )
    latest_report = fields.Nested(
        LatestHealthReportSchema,
        required=True,
        allow_none=True,
        metadata={"description": "The Health Report with the newest `timestamp`."},
    )
    hygiene = fields.Nested(
        HygieneSchema,
        required=True,
        allow_none=True,
        metadata={"description": "Null until a scoring run has scored the Station."},
    )
    scored_at = fields.AwareDateTime(
        required=True,
        allow_none=True,
        metadata={"description": "When the last scoring run completed. Null before the first run."},
    )
