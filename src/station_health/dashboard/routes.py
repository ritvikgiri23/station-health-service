"""GET /dashboard: the operator's one-page view. No build step and no API key to load it.

The page itself is public; its data comes from `read`-role endpoints, called from the
browser with a key. With DASHBOARD_DEMO_KEY set (docker-compose sets it for local use),
the page carries that read-only key so it works without one being typed in. A plain
Flask blueprint, so the page stays out of the OpenAPI document.
"""

from flask import Blueprint, Response, make_response, redirect, render_template, url_for
from werkzeug.wrappers import Response as BaseResponse

from station_health.auth.api_keys import API_KEY_HEADER
from station_health.runtime import current_settings

blp = Blueprint(
    "dashboard",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/dashboard/static",
)


@blp.get("/")
def home() -> BaseResponse:
    return redirect(url_for("dashboard.dashboard"))


@blp.get("/dashboard")
def dashboard() -> Response:
    demo_key = current_settings().dashboard_demo_key
    response = make_response(
        render_template("dashboard.html", demo_key=demo_key or "", key_header=API_KEY_HEADER)
    )
    if demo_key:
        # The page carries a key: keep it out of shared and browser caches.
        response.headers["Cache-Control"] = "no-store"
    return response
