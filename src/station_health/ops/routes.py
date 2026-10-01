"""Liveness and readiness checks for the container orchestrator. No authentication."""

import logging
from typing import Any

from flask.views import MethodView
from flask_smorest import Blueprint
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from station_health.extensions import db
from station_health.ops.schemas import LivenessSchema, ReadinessSchema

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
        """Readiness: the service can reach its database."""
        if _database_reachable():
            return {"status": "ok", "checks": {"database": "ok"}}, 200
        return {"status": "unavailable", "checks": {"database": "unreachable"}}, 503


def _database_reachable() -> bool:
    try:
        with db.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.warning("readiness check could not reach the database", exc_info=True)
        return False
    return True
