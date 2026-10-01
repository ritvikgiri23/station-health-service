import pytest

from station_health.app import create_app
from station_health.config import ConfigError, Settings


def test_service_refuses_to_start_without_a_database_url() -> None:
    with pytest.raises(ConfigError, match="DATABASE_URL"):
        create_app(Settings.from_env({}))


def test_service_refuses_to_start_with_an_unknown_log_level() -> None:
    with pytest.raises(ConfigError, match="LOG_LEVEL"):
        create_app(
            Settings.from_env({"DATABASE_URL": "mysql+pymysql://u:p@h/db", "LOG_LEVEL": "LOUD"})
        )


@pytest.mark.parametrize(
    "setting",
    [
        "INGEST_FUTURE_TOLERANCE_SECONDS",
        "RAW_RETENTION_HOURS",
        "SCORING_WINDOW_MINUTES",
        "WORKER_INTERVAL_SECONDS",
    ],
)
@pytest.mark.parametrize("value", ["soon", "-5", "0"])
def test_service_refuses_to_start_with_a_non_positive_duration(setting: str, value: str) -> None:
    with pytest.raises(ConfigError, match=setting):
        create_app(Settings.from_env({"DATABASE_URL": "mysql+pymysql://u:p@h/db", setting: value}))


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"LATENCY_GOOD_MS": "fast"}, "LATENCY_GOOD_MS"),
        ({"LATENCY_BAD_MS": "-1"}, "LATENCY_BAD_MS"),
        ({"LATENCY_GOOD_MS": "1000", "LATENCY_BAD_MS": "150"}, "LATENCY_BAD_MS"),
        ({"ERROR_LIMIT_PER_REPORT": "0"}, "ERROR_LIMIT_PER_REPORT"),
        ({"ERROR_LIMIT_PER_REPORT": "nan"}, "ERROR_LIMIT_PER_REPORT"),
        ({"LATENCY_WEIGHT": "0.5"}, "LATENCY_WEIGHT and ERROR_WEIGHT"),
    ],
)
def test_service_refuses_to_start_with_invalid_scoring_settings(
    overrides: dict[str, str], message: str
) -> None:
    with pytest.raises(ConfigError, match=message):
        Settings.from_env({"DATABASE_URL": "mysql+pymysql://u:p@h/db", **overrides})


def test_scoring_weights_are_configurable_together() -> None:
    settings = Settings.from_env(
        {"DATABASE_URL": "mysql+pymysql://u:p@h/db", "LATENCY_WEIGHT": "0.3", "ERROR_WEIGHT": "0.7"}
    )

    assert settings.scoring.latency_weight == 0.3
    assert settings.scoring.error_weight == 0.7
