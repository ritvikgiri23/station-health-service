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


@pytest.mark.parametrize("setting", ["INGEST_FUTURE_TOLERANCE_SECONDS", "RAW_RETENTION_HOURS"])
@pytest.mark.parametrize("value", ["soon", "-5", "0"])
def test_service_refuses_to_start_with_a_non_positive_duration(setting: str, value: str) -> None:
    with pytest.raises(ConfigError, match=setting):
        create_app(Settings.from_env({"DATABASE_URL": "mysql+pymysql://u:p@h/db", setting: value}))
