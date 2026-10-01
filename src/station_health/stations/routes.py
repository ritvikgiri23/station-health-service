"""Station Registry management (role `admin`)."""

from typing import Any

from flask.views import MethodView
from flask_smorest import Blueprint

from station_health.auth.api_keys import require_role
from station_health.auth.roles import Role
from station_health.errors import abort
from station_health.paging import InvalidCursor
from station_health.runtime import current_time
from station_health.stations.models import Station
from station_health.stations.registry import (
    StationPage,
    delete_station,
    find_station,
    list_stations,
    register_station,
)
from station_health.stations.schemas import (
    STATION_ID_MAX_LENGTH,
    StationListQuerySchema,
    StationPageSchema,
    StationRegistrationSchema,
    StationSchema,
)

blp = Blueprint("stations", __name__, description="Station Registry")


@blp.route("/stations")
class Stations(MethodView):
    @require_role(blp, Role.ADMIN)
    @blp.arguments(StationListQuerySchema, location="query", as_kwargs=True)
    @blp.response(200, StationPageSchema)
    @blp.alt_response(400, response="BAD_REQUEST")
    def get(
        self, limit: int, cursor: str | None = None, verified: bool | None = None
    ) -> StationPage:
        """The Station Registry by `station_id`; `verified=false` lists Unverified Stations."""
        try:
            return list_stations(verified, limit, cursor)
        except InvalidCursor:
            abort(400, "The cursor is not valid.")


@blp.route("/stations/<station_id>")
class StationEntry(MethodView):
    @require_role(blp, Role.ADMIN)
    @blp.response(200, StationSchema)
    @blp.alt_response(404, response="NOT_FOUND")
    def get(self, station_id: str) -> Station:
        """A Station's Station Registry entry."""
        station = find_station(station_id)
        if station is None:
            abort(404, f"Station {station_id!r} is not in the Station Registry.")
        return station

    @require_role(blp, Role.ADMIN)
    @blp.arguments(StationRegistrationSchema)
    @blp.response(201, StationSchema, description="Station registered")
    @blp.alt_response(200, schema=StationSchema, description="Station updated")
    def put(self, registration: dict[str, Any], station_id: str) -> tuple[Station, int]:
        """Register or update a Station with its Region. Marks it verified.

        Idempotent. Registering an Unverified Station confirms it.
        """
        if len(station_id) > STATION_ID_MAX_LENGTH:
            abort(422, f"station_id must be at most {STATION_ID_MAX_LENGTH} characters.")
        station, created = register_station(station_id, registration["region"], current_time())
        return station, 201 if created else 200

    @require_role(blp, Role.ADMIN)
    @blp.response(204, description="Station deleted")
    @blp.alt_response(404, response="NOT_FOUND")
    def delete(self, station_id: str) -> None:
        """Delete a Station from the Station Registry.

        Its Health Reports stay until they age out. A later Health Report for it registers
        it again, as an Unverified Station.
        """
        if not delete_station(station_id):
            abort(404, f"Station {station_id!r} is not in the Station Registry.")
