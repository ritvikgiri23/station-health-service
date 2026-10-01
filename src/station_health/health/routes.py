"""Station health status and the Poor Hygiene list (role `read`)."""

from flask.views import MethodView
from flask_smorest import Blueprint

from station_health.auth.api_keys import require_role
from station_health.auth.roles import Role
from station_health.errors import abort
from station_health.health.poor_hygiene import (
    InvalidCursor,
    PoorHygieneFilters,
    PoorHygienePage,
    PoorHygieneSort,
    list_poor_hygiene,
)
from station_health.health.schemas import (
    PoorHygienePageSchema,
    PoorHygieneQuerySchema,
    StationHealthStatusSchema,
)
from station_health.health.status import StationHealthStatus, station_health_status
from station_health.scoring import FlagReason

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


@blp.route("/poor-hygiene")
class PoorHygieneList(MethodView):
    @require_role(blp, Role.READ)
    @blp.arguments(PoorHygieneQuerySchema, location="query", as_kwargs=True)
    @blp.response(200, PoorHygienePageSchema)
    @blp.alt_response(400, response="BAD_REQUEST")
    def get(
        self,
        sort: PoorHygieneSort,
        limit: int,
        cursor: str | None = None,
        region: str | None = None,
        flag_reason: FlagReason | None = None,
        verified: bool | None = None,
    ) -> PoorHygienePage:
        """Stations with Poor Hygiene, worst Hygiene Score first.

        Silent Stations sort as score 0; ties go to the oldest "flagged since". Paged by
        an opaque cursor that holds the last Station's sort key, so pages stay consistent
        while the worker rescores Stations every minute.
        """
        try:
            return list_poor_hygiene(
                PoorHygieneFilters(region, flag_reason, verified), sort, limit, cursor
            )
        except InvalidCursor:
            abort(400, "The cursor is not valid.")
