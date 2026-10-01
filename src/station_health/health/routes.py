"""Station health status (role `read`)."""

from flask.views import MethodView
from flask_smorest import Blueprint

from station_health.auth.api_keys import require_role
from station_health.auth.roles import Role
from station_health.errors import abort
from station_health.health.schemas import StationHealthStatusSchema
from station_health.health.status import StationHealthStatus, station_health_status

blp = Blueprint("health", __name__, description="Station health and Hygiene Scores")


@blp.route("/stations/<station_id>/health")
class StationHealthEntry(MethodView):
    @require_role(blp, Role.READ)
    @blp.response(200, StationHealthStatusSchema)
    @blp.alt_response(404, response="NOT_FOUND")
    def get(self, station_id: str) -> StationHealthStatus:
        """A Station's latest health status: latest Health Report and Hygiene Score.

        Scores come from the last scoring run, which the worker repeats every
        WORKER_INTERVAL_SECONDS; `scored_at` says when that was.
        """
        status = station_health_status(station_id)
        if status is None:
            abort(404, f"Station {station_id!r} is unknown.")
        return status
