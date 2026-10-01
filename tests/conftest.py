"""Integration test harness: the real Flask app against a real MySQL 8 from Testcontainers."""

from collections.abc import Iterator

import pytest
from flask import Flask
from flask.testing import FlaskClient
from flask_migrate import upgrade
from testcontainers.community.mysql import MySqlContainer

from station_health.app import create_app
from station_health.config import Settings

MYSQL_IMAGE = "mysql:8.4"


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    with MySqlContainer(MYSQL_IMAGE, dialect="pymysql") as mysql:
        yield mysql.get_connection_url()


@pytest.fixture(scope="session")
def settings(database_url: str) -> Settings:
    return Settings.from_env({"DATABASE_URL": database_url, "LOG_LEVEL": "WARNING"})


@pytest.fixture(scope="session")
def app(settings: Settings) -> Flask:
    app = create_app(settings)
    with app.app_context():
        upgrade()
    return app


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    return app.test_client()
