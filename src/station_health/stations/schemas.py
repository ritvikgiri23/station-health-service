from marshmallow import Schema, fields


class StationSchema(Schema):
    station_id = fields.String(required=True)
    region = fields.String(required=True, allow_none=True)
    verified = fields.Boolean(
        required=True, metadata={"description": "False for an Unverified Station."}
    )
