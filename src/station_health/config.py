"""Settings read from environment variables. `.env.example` documents every one."""

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta

from station_health.auth.roles import Role
from station_health.scoring import ScoringConfig

LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

# Each variable holds a comma-separated list of keys granted that role.
API_KEY_VARIABLES = {
    Role.INGEST: "API_KEYS_INGEST",
    Role.READ: "API_KEYS_READ",
    Role.ADMIN: "API_KEYS_ADMIN",
}


DEFAULT_INGEST_FUTURE_TOLERANCE = timedelta(minutes=5)
DEFAULT_RAW_RETENTION = timedelta(hours=48)
DEFAULT_SCORING_WINDOW = timedelta(minutes=15)
DEFAULT_WORKER_INTERVAL = timedelta(seconds=60)
DEFAULT_SCORING = ScoringConfig()


class ConfigError(ValueError):
    """Raised when the environment does not describe a valid configuration."""


@dataclass(frozen=True)
class Settings:
    database_url: str
    log_level: str = "INFO"
    api_keys: Mapping[str, frozenset[Role]] = field(default_factory=dict)
    ingest_future_tolerance: timedelta = DEFAULT_INGEST_FUTURE_TOLERANCE
    raw_retention: timedelta = DEFAULT_RAW_RETENTION
    scoring_window: timedelta = DEFAULT_SCORING_WINDOW
    worker_interval: timedelta = DEFAULT_WORKER_INTERVAL
    scoring: ScoringConfig = DEFAULT_SCORING

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if environ is None else environ

        database_url = env.get("DATABASE_URL", "").strip()
        if not database_url:
            raise ConfigError("DATABASE_URL is required")

        log_level = env.get("LOG_LEVEL", "INFO").strip().upper()
        if log_level not in LOG_LEVELS:
            raise ConfigError(f"LOG_LEVEL must be one of {', '.join(LOG_LEVELS)}")

        return cls(
            database_url=database_url,
            log_level=log_level,
            api_keys=_api_keys(env),
            ingest_future_tolerance=timedelta(
                seconds=_positive_int(
                    env,
                    "INGEST_FUTURE_TOLERANCE_SECONDS",
                    int(DEFAULT_INGEST_FUTURE_TOLERANCE.total_seconds()),
                )
            ),
            raw_retention=timedelta(
                hours=_positive_int(
                    env, "RAW_RETENTION_HOURS", int(DEFAULT_RAW_RETENTION.total_seconds()) // 3600
                )
            ),
            scoring_window=timedelta(
                minutes=_positive_int(
                    env, "SCORING_WINDOW_MINUTES", int(DEFAULT_SCORING_WINDOW.total_seconds()) // 60
                )
            ),
            worker_interval=timedelta(
                seconds=_positive_int(
                    env, "WORKER_INTERVAL_SECONDS", int(DEFAULT_WORKER_INTERVAL.total_seconds())
                )
            ),
            scoring=_scoring(env),
        )


def _scoring(env: Mapping[str, str]) -> ScoringConfig:
    latency_good_ms = _non_negative_float(env, "LATENCY_GOOD_MS", DEFAULT_SCORING.latency_good_ms)
    latency_bad_ms = _non_negative_float(env, "LATENCY_BAD_MS", DEFAULT_SCORING.latency_bad_ms)
    if latency_bad_ms <= latency_good_ms:
        raise ConfigError("LATENCY_BAD_MS must be greater than LATENCY_GOOD_MS")
    error_limit = _non_negative_float(env, "ERROR_LIMIT_PER_REPORT", DEFAULT_SCORING.error_limit)
    if error_limit == 0:
        raise ConfigError("ERROR_LIMIT_PER_REPORT must be greater than 0")
    latency_weight = _non_negative_float(env, "LATENCY_WEIGHT", DEFAULT_SCORING.latency_weight)
    error_weight = _non_negative_float(env, "ERROR_WEIGHT", DEFAULT_SCORING.error_weight)
    # Weights summing to 1 keep the Hygiene Score within 0-100.
    if not math.isclose(latency_weight + error_weight, 1.0):
        raise ConfigError("LATENCY_WEIGHT and ERROR_WEIGHT must add up to 1")
    return ScoringConfig(
        latency_good_ms=latency_good_ms,
        latency_bad_ms=latency_bad_ms,
        error_limit=error_limit,
        latency_weight=latency_weight,
        error_weight=error_weight,
    )


def _api_keys(env: Mapping[str, str]) -> dict[str, frozenset[Role]]:
    roles_by_key: dict[str, set[Role]] = {}
    for role, variable in API_KEY_VARIABLES.items():
        for key in env.get(variable, "").split(","):
            if key.strip():
                roles_by_key.setdefault(key.strip(), set()).add(role)
    return {key: frozenset(roles) for key, roles in roles_by_key.items()}


def _positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a positive integer") from None
    if value <= 0:
        raise ConfigError(f"{name} must be a positive integer")
    return value


def _non_negative_float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a non-negative number") from None
    if not math.isfinite(value) or value < 0:
        raise ConfigError(f"{name} must be a non-negative number")
    return value
