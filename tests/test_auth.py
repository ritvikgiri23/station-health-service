"""Role-scoped API keys: 401 without a valid key, 403 without the required role."""

from collections.abc import Callable

import pytest
from flask.testing import FlaskClient

from tests.support import ADMIN_KEY, INGEST_KEY, READ_KEY, auth, health_report


def test_ingest_without_an_api_key_is_unauthenticated(client: FlaskClient) -> None:
    response = client.post("/health-reports", json=health_report())

    assert response.status_code == 401
    assert response.json["code"] == 401
    assert response.json["status"] == "Unauthorized"
    assert response.json["message"]


def test_ingest_with_an_unknown_api_key_is_unauthenticated(client: FlaskClient) -> None:
    response = client.post("/health-reports", json=health_report(), headers=auth("nope"))

    assert response.status_code == 401


@pytest.mark.parametrize("key", [READ_KEY, ADMIN_KEY])
def test_ingest_with_a_key_lacking_the_ingest_role_is_forbidden(
    client: FlaskClient, key: str
) -> None:
    response = client.post("/health-reports", json=health_report(), headers=auth(key))

    assert response.status_code == 403
    assert response.json["code"] == 403
    assert response.json["status"] == "Forbidden"


def test_authentication_is_checked_before_the_payload(client: FlaskClient) -> None:
    response = client.post("/health-reports", json={"bad": "payload"})

    assert response.status_code == 401


@pytest.mark.parametrize("key", [INGEST_KEY, READ_KEY])
def test_reading_the_station_registry_requires_the_admin_role(
    client: FlaskClient, key: str
) -> None:
    assert client.get("/stations/ST-0001", headers=auth(key)).status_code == 403
    assert client.get("/stations/ST-0001").status_code == 401


def test_keys_and_their_roles_come_from_configuration(
    make_client: Callable[..., FlaskClient],
) -> None:
    client = make_client(
        API_KEYS_INGEST="first-key, second-key", API_KEYS_READ="", API_KEYS_ADMIN=""
    )

    assert (
        client.post("/health-reports", json=health_report(), headers=auth("second-key")).status_code
        == 201
    )
    assert (
        client.post("/health-reports", json=health_report(), headers=auth(INGEST_KEY)).status_code
        == 401
    )


def test_one_key_can_hold_several_roles(make_client: Callable[..., FlaskClient]) -> None:
    client = make_client(API_KEYS_INGEST="ops-key", API_KEYS_ADMIN="ops-key")

    assert (
        client.post("/health-reports", json=health_report(), headers=auth("ops-key")).status_code
        == 201
    )
    assert client.get("/stations/ST-0001", headers=auth("ops-key")).status_code == 200
