"""Liveness and readiness checks for the container orchestrator. No authentication."""

import logging
from datetime import datetime
from typing import Any

from flask.views import MethodView
from flask_smorest import Blueprint
from sqlalchemy.exc import SQLAlchemyError

from station_health.health.status import last_scored_at
from station_health.ops.schemas import LivenessSchema, ReadinessSchema, ScoringFreshness
from station_health.runtime import current_settings, current_time

logger = logging.getLogger(__name__)

blp = Blueprint("ops", __name__, description="Service liveness and readiness")


@blp.route("/livez")
class Liveness(MethodView):
    @blp.response(200, LivenessSchema)
    def get(self) -> dict[str, Any]:
        """Liveness: the process is up and serving requests."""
        return {"status": "ok"}


@blp.route("/readyz")
class Readiness(MethodView):
    @blp.response(200, ReadinessSchema)
    @blp.alt_response(503, schema=ReadinessSchema, description="A dependency is unavailable")
    def get(self) -> tuple[dict[str, Any], int]:
        """Readiness: the service can reach its database, and its scores are fresh.

        `503` when the database is unreachable. When the last scoring run is older than
        SCORING_STALE_AFTER_SECONDS, or there has been none, the status is `degraded` but
        the response is still `200`: the API can serve, so it stays in rotation, while a
        stuck or dead worker is visible. A `503` before the first scoring run would also
        deadlock docker-compose, where the worker waits for the API to be healthy.
        """
        try:
            # Reading the scoring-run record is also the database check.
            scored_at = last_scored_at()
        except SQLAlchemyError:
            logger.warning("readiness check could not reach the database", exc_info=True)
            return {
                "status": "unavailable",
                "checks": {"database": "unreachable", "scoring": ScoringFreshness.UNKNOWN},
                "scored_at": None,
            }, 503
        scoring = _scoring_freshness(scored_at)
        return {
            "status": "ok" if scoring is ScoringFreshness.OK else "degraded",
            "checks": {"database": "ok", "scoring": scoring},
            "scored_at": scored_at,
        }, 200


def _scoring_freshness(scored_at: datetime | None) -> ScoringFreshness:
    if scored_at is None:
        return ScoringFreshness.NEVER_RUN
    if current_time() - scored_at > current_settings().scoring_stale_after:
        return ScoringFreshness.STALE
    return ScoringFreshness.OK
