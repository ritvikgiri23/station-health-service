from marshmallow import Schema, fields


class LivenessSchema(Schema):
    status = fields.String(required=True, metadata={"example": "ok"})


class ReadinessChecksSchema(Schema):
    database = fields.String(
        required=True, metadata={"description": "`ok` or `unreachable`", "example": "ok"}
    )


class ReadinessSchema(Schema):
    status = fields.String(
        required=True, metadata={"description": "`ok` or `unavailable`", "example": "ok"}
    )
    checks = fields.Nested(ReadinessChecksSchema, required=True)
