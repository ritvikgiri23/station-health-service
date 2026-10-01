"""Integration test harness: the real Flask app against a real MySQL 8 from Testcontainers."""

from collections.abc import Callable, Iterator
from datetime import datetime

import pytest
from flask import Flask
from flask.testing import FlaskClient
from flask_migrate import upgrade
from sqlalchemy import text
from testcontainers.community.mysql import MySqlContainer

from station_health.app import create_app
from station_health.config import Settings
from station_health.extensions import db
from station_health.worker.scoring_run import ScoringRun, run_scoring_once
from tests.support import START, TEST_API_KEYS, FakeClock

MYSQL_IMAGE = "mysql:8.4"


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    with MySqlContainer(MYSQL_IMAGE, dialect="pymysql") as mysql:
        yield mysql.get_connection_url()


@pytest.fixture(scope="session")
def test_env(database_url: str) -> dict[str, str]:
    return {"DATABASE_URL": database_url, "LOG_LEVEL": "WARNING", **TEST_API_KEYS}


@pytest.fixture(scope="session")
def settings(test_env: dict[str, str]) -> Settings:
    return Settings.from_env(test_env)


@pytest.fixture(scope="session")
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture(scope="session")
def migrated_app(settings: Settings, clock: FakeClock) -> Flask:
    app = create_app(settings, clock=clock)
    with app.app_context():
        upgrade()
    return app


@pytest.fixture
def app(migrated_app: Flask, clock: FakeClock) -> Flask:
    """The shared app, with an empty database and the clock back at START."""
    clock.now = START
    with migrated_app.app_context():
        tables = [t.name for t in db.metadata.sorted_tables]
        with db.engine.begin() as connection:
            for table in tables:
                connection.execute(text(f"DELETE FROM `{table}`"))
    return migrated_app


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    return app.test_client()


@pytest.fixture
def make_client(test_env: dict[str, str], app: Flask) -> Callable[..., FlaskClient]:
    """A client for an app with some settings overridden, sharing the (emptied) test database."""

    def build(**overrides: str) -> FlaskClient:
        settings = Settings.from_env({**test_env, **overrides})
        return create_app(settings, clock=FakeClock(START)).test_client()

    return build


@pytest.fixture
def run_worker(app: Flask) -> Callable[[datetime], ScoringRun]:
    """Run the worker's scoring run once, as of `now`."""

    def run(now: datetime) -> ScoringRun:
        with app.app_context():
            return run_scoring_once(now)

    return run
