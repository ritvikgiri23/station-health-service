"""Flask app factory. Run with `gunicorn "station_health.app:create_app()"`."""

from pathlib import Path

from flask import Flask

from station_health.config import Settings
from station_health.extensions import api, db, migrate
from station_health.log import configure_logging, init_request_logging
from station_health.ops.routes import blp as ops_blp

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
DATABASE_TIMEOUT_SECONDS = 3


def create_app(settings: Settings | None = None) -> Flask:
    settings = settings or Settings.from_env()
    configure_logging(settings.log_level)

    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI=settings.database_url,
        SQLALCHEMY_ENGINE_OPTIONS={
            "pool_pre_ping": True,
            "connect_args": {
                "connect_timeout": DATABASE_TIMEOUT_SECONDS,
                "read_timeout": DATABASE_TIMEOUT_SECONDS,
                "write_timeout": DATABASE_TIMEOUT_SECONDS,
            },
        },
        API_TITLE="Station Health Service",
        API_VERSION="1.0.0",
        OPENAPI_VERSION="3.0.3",
        OPENAPI_URL_PREFIX="/",
        OPENAPI_JSON_PATH="openapi.json",
        OPENAPI_SWAGGER_UI_PATH="/docs",
        OPENAPI_SWAGGER_UI_URL="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/",
    )

    db.init_app(app)
    migrate.init_app(app, db, directory=str(MIGRATIONS_DIR))
    api.init_app(app)
    init_request_logging(app)

    api.register_blueprint(ops_blp)

    return app
