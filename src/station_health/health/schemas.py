from marshmallow import Schema, fields
from marshmallow.validate import Range

from station_health.health.poor_hygiene import PoorHygieneSort
from station_health.paging import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from station_health.reports.models import ConnectivityStatus
from station_health.scoring import FlagReason


def scored_at_field() -> fields.AwareDateTime:
    return fields.AwareDateTime(
        required=True,
        allow_none=True,
        metadata={"description": "When the last scoring run completed. Null before the first run."},
    )


class LatestHealthReportSchema(Schema):
    timestamp = fields.AwareDateTime(required=True)
    connectivity_status = fields.Enum(ConnectivityStatus, by_value=True, required=True)
    latency_ms = fields.Float(required=True)
    error_count = fields.Integer(required=True)
    firmware_version = fields.String(required=True)


class HygieneSchema(Schema):
    score = fields.Integer(
        required=True,
        allow_none=True,
        attribute="hygiene_score",
        metadata={
            "description": "Hygiene Score, 0-100: Availability x weighted quality x 100. "
            "Null while Silent."
        },
    )
    availability = fields.Float(
        required=True,
        allow_none=True,
        metadata={
            "description": "Share of Health Reports in the Scoring Window not Offline, 0-1. "
            "Null while Silent."
        },
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
        required=True,
        metadata={
            "description": "Health Reports in the Scoring Window. Like the other parts, it is "
            "as of the last scoring run that changed the score, Silent, Poor Hygiene or "
            "Flag Reason."
        },
    )
    silent = fields.Boolean(
        required=True,
        metadata={"description": "True when the Scoring Window holds no Health Reports."},
    )
    poor_hygiene = fields.Boolean(
        required=True,
        metadata={
            "description": "Entered when Silent or below the Flag Threshold; left only when "
            "not Silent, at or above the Clear Threshold, with enough Health Reports."
        },
    )
    flag_reason = fields.Enum(
        FlagReason,
        by_value=True,
        required=True,
        allow_none=True,
        metadata={
            "description": "Why the Station has Poor Hygiene: `silent`, or the lowest of "
            "Availability, latency score and error score. Null without Poor Hygiene."
        },
    )
    flagged_since = fields.AwareDateTime(
        required=True,
        allow_none=True,
        metadata={"description": "When the Station entered Poor Hygiene. Null without it."},
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
    scored_at = scored_at_field()


class PoorHygieneQuerySchema(Schema):
    region = fields.String(metadata={"description": "Only Stations in this Region."})
    flag_reason = fields.Enum(
        FlagReason, by_value=True, metadata={"description": "Only Stations with this Flag Reason."}
    )
    verified = fields.Boolean(
        metadata={"description": "Only verified (true) or Unverified (false) Stations."}
    )
    sort = fields.Enum(
        PoorHygieneSort,
        by_value=True,
        load_default=PoorHygieneSort.SCORE,
        metadata={
            "description": "`score`: worst Hygiene Score first (Silent as 0), then oldest "
            '"flagged since". `flagged_since` / `-flagged_since`: oldest / newest "flagged '
            'since" first, then worst score.'
        },
    )
    limit = fields.Integer(
        load_default=DEFAULT_PAGE_SIZE,
        validate=Range(min=1, max=MAX_PAGE_SIZE),
        metadata={"description": f"Stations per page, at most {MAX_PAGE_SIZE}."},
    )
    cursor = fields.String(
        metadata={
            "description": "The `next_cursor` of the previous page, with the same filters "
            "and sort. Opaque."
        }
    )


class PoorHygieneStationSchema(Schema):
    station_id = fields.String(required=True)
    region = fields.String(required=True, allow_none=True)
    verified = fields.Boolean(
        required=True, metadata={"description": "False for an Unverified Station."}
    )
    score = fields.Integer(
        required=True,
        allow_none=True,
        metadata={"description": "Hygiene Score, 0-100. Null while Silent; sorted as 0."},
    )
    silent = fields.Boolean(required=True)
    flag_reason = fields.Enum(FlagReason, by_value=True, required=True)
    flagged_since = fields.AwareDateTime(
        required=True, metadata={"description": "When the Station entered Poor Hygiene."}
    )


class PoorHygienePageSchema(Schema):
    items = fields.List(fields.Nested(PoorHygieneStationSchema), required=True)
    total = fields.Integer(
        required=True,
        metadata={"description": "Stations with Poor Hygiene matching the filters, on all pages."},
    )
    next_cursor = fields.String(
        required=True,
        allow_none=True,
        metadata={"description": "Pass as `cursor` for the next page. Null on the last page."},
    )
    scored_at = scored_at_field()
