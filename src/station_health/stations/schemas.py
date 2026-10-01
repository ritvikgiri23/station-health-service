from marshmallow import Schema, fields
from marshmallow.validate import Length, Range

from station_health.paging import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

STATION_ID_MAX_LENGTH = 64
REGION_MAX_LENGTH = 64


class StationSchema(Schema):
    station_id = fields.String(required=True)
    region = fields.String(required=True, allow_none=True)
    verified = fields.Boolean(
        required=True, metadata={"description": "False for an Unverified Station."}
    )


class StationRegistrationSchema(Schema):
    region = fields.String(
        required=True,
        allow_none=True,
        validate=Length(min=1, max=REGION_MAX_LENGTH),
        metadata={"description": "The Station's Region, or null for none."},
    )


class StationListQuerySchema(Schema):
    verified = fields.Boolean(
        metadata={"description": "Only verified (true) or Unverified (false) Stations."}
    )
    limit = fields.Integer(
        load_default=DEFAULT_PAGE_SIZE,
        validate=Range(min=1, max=MAX_PAGE_SIZE),
        metadata={"description": f"Stations per page, at most {MAX_PAGE_SIZE}."},
    )
    cursor = fields.String(
        metadata={
            "description": "The `next_cursor` of the previous page, with the same filter. Opaque."
        }
    )


class StationPageSchema(Schema):
    items = fields.List(fields.Nested(StationSchema), required=True)
    next_cursor = fields.String(
        required=True,
        allow_none=True,
        metadata={"description": "Pass as `cursor` for the next page. Null on the last page."},
    )
