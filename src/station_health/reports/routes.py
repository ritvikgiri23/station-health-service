"""Health Report ingest (role `ingest`)."""

from flask.views import MethodView
from flask_smorest import Blueprint

from station_health.auth.api_keys import require_role
from station_health.auth.roles import Role
from station_health.reports.ingest import record_health_report
from station_health.reports.models import HealthReport
from station_health.reports.schemas import HealthReportSchema
from station_health.runtime import current_time

blp = Blueprint("reports", __name__, description="Health Reports from the Collector")


@blp.route("/health-reports")
class HealthReports(MethodView):
    @require_role(blp, Role.INGEST)
    @blp.arguments(HealthReportSchema)
    @blp.response(201, HealthReportSchema, description="Health Report stored")
    @blp.alt_response(
        200,
        schema=HealthReportSchema,
        description="Already stored (same `station_id` and `timestamp`); "
        "nothing was written and the stored Health Report is returned",
    )
    def post(self, report: HealthReport) -> tuple[HealthReport, int]:
        """Submit one Health Report.

        A Station not yet in the Station Registry is registered as an Unverified Station.
        """
        stored, created = record_health_report(report, received_at=current_time())
        return stored, 201 if created else 200
