"""Aggregated fleet metrics (role `read`)."""

from flask.views import MethodView
from flask_smorest import Blueprint

from station_health.auth.api_keys import require_role
from station_health.auth.roles import Role
from station_health.metrics.schemas import MetricsSnapshotQuerySchema, MetricsSnapshotSchema
from station_health.metrics.snapshot import MetricsGrouping, MetricsSnapshot, metrics_snapshot

blp = Blueprint("metrics", __name__, description="Aggregated fleet health metrics")


@blp.route("/metrics")
class MetricsSnapshotEntry(MethodView):
    @require_role(blp, Role.READ)
    @blp.arguments(MetricsSnapshotQuerySchema, location="query", as_kwargs=True)
    @blp.response(200, MetricsSnapshotSchema)
    def get(self, group_by: MetricsGrouping | None = None) -> MetricsSnapshot:
        """Current fleet health: station, Poor Hygiene, Silent and Unverified Station counts
        and average Hygiene Score, Availability and p95 latency.

        Overall, and optionally per Region or per firmware version. Built from Station
        health as of the last scoring run, never from raw Health Reports; `scored_at` says
        when that run was.
        """
        return metrics_snapshot(group_by)
