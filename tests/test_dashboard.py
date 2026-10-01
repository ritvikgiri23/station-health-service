"""The dashboard: one static page served by the API that calls only `read`-role endpoints."""

import re
from collections.abc import Callable

from flask.testing import FlaskClient

from tests.support import INGEST_KEY, READ_KEY, auth

DASHBOARD = "/dashboard"


def assets(client: FlaskClient, page: str) -> dict[str, str]:
    """The page's scripts and stylesheets by URL, each fetched without an API key."""
    urls = re.findall(r'<(?:script[^>]*\bsrc|link[^>]*\bhref)="([^"]+)"', page)
    fetched = {}
    for url in urls:
        response = client.get(url)
        assert response.status_code == 200, url
        fetched[url] = response.get_data(as_text=True)
    return fetched


def api_paths(source: str) -> set[str]:
    """Every string literal in `source` that looks like a path on this service, without
    its query string, leaving out the dashboard's own files.
    """
    literals = re.findall(r"""["'`](/[A-Za-z][^"'`\s]*)""", source)
    paths = {literal.split("?")[0] for literal in literals}
    return {p for p in paths if not p.startswith(DASHBOARD)}


def test_the_dashboard_is_served_without_an_api_key(client: FlaskClient) -> None:
    response = client.get(DASHBOARD)

    assert response.status_code == 200
    assert response.mimetype == "text/html"
    page = response.get_data(as_text=True)
    assert "<title>" in page
    # No build step: the page loads its own plain scripts and stylesheet.
    assert any(url.endswith(".js") for url in assets(client, page))


def test_the_dashboard_calls_only_read_role_endpoints(client: FlaskClient) -> None:
    page = client.get(DASHBOARD).get_data(as_text=True)
    sources = [page, *assets(client, page).values()]
    paths = set().union(*(api_paths(source) for source in sources))

    # Summary tiles, the Poor Hygiene list and the trend chart.
    assert paths == {"/metrics", "/poor-hygiene", "/metrics/trend"}
    for path in paths:
        assert client.get(path, headers=auth(READ_KEY)).status_code == 200, path
        assert client.get(path, headers=auth(INGEST_KEY)).status_code == 403, path


def test_a_configured_demo_key_is_injected_into_the_page_and_not_cached(
    make_client: Callable[..., FlaskClient],
) -> None:
    client = make_client(DASHBOARD_DEMO_KEY=READ_KEY)

    response = client.get(DASHBOARD)

    assert READ_KEY in response.get_data(as_text=True)
    assert "no-store" in response.headers["Cache-Control"]


def test_without_a_demo_key_the_page_carries_no_key(client: FlaskClient) -> None:
    page = client.get(DASHBOARD).get_data(as_text=True)

    assert READ_KEY not in page
    assert INGEST_KEY not in page


def test_the_root_redirects_to_the_dashboard(client: FlaskClient) -> None:
    response = client.get("/")

    assert response.status_code == 302
    assert response.headers["Location"] == DASHBOARD
