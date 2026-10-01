from enum import StrEnum

from marshmallow import Schema, fields

from station_health.health.schemas import scored_at_field


class LivenessSchema(Schema):
    status = fields.String(required=True, metadata={"example": "ok"})


class ScoringFreshness(StrEnum):
    OK = "ok"
    # The last scoring run is older than SCORING_STALE_AFTER_SECONDS.
    STALE = "stale"
    NEVER_RUN = "never_run"
    # The database is unreachable, so the scoring-run record could not be read.
    UNKNOWN = "unknown"


class ReadinessChecksSchema(Schema):
    database = fields.String(
        required=True, metadata={"description": "`ok` or `unreachable`", "example": "ok"}
    )
    scoring = fields.Enum(
        ScoringFreshness,
        by_value=True,
        required=True,
        metadata={"description": "Whether the last scoring run is recent enough"},
    )


class ReadinessSchema(Schema):
    status = fields.String(
        required=True,
        metadata={
            "description": "`ok`, `degraded` (scores are not fresh) or `unavailable`",
            "example": "ok",
        },
    )
    checks = fields.Nested(ReadinessChecksSchema, required=True)
    scored_at = scored_at_field()
