"""Station Registry endpoints (role `admin`)."""

from flask.views import MethodView
from flask_smorest import Blueprint

from station_health.auth.api_keys import require_role
from station_health.auth.roles import Role
from station_health.errors import abort
from station_health.stations.models import Station
from station_health.stations.registry import find_station
from station_health.stations.schemas import StationSchema

blp = Blueprint("stations", __name__, description="Station Registry")


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
