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
DEFAULT_SUMMARY_RETENTION = timedelta(days=30)
DEFAULT_RETENTION_BATCH_SIZE = 10_000
DEFAULT_SCORING_WINDOW = timedelta(minutes=15)
DEFAULT_WORKER_INTERVAL = timedelta(seconds=60)
DEFAULT_SCORING_STALE_AFTER = timedelta(minutes=3)
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
    summary_retention: timedelta = DEFAULT_SUMMARY_RETENTION
    # Rows deleted per statement by retention clean-up.
    retention_batch_size: int = DEFAULT_RETENTION_BATCH_SIZE
    scoring_window: timedelta = DEFAULT_SCORING_WINDOW
    worker_interval: timedelta = DEFAULT_WORKER_INTERVAL
    # Readiness reports degraded when the last scoring run is older than this.
    scoring_stale_after: timedelta = DEFAULT_SCORING_STALE_AFTER
    scoring: ScoringConfig = DEFAULT_SCORING
    # A read-only key the dashboard page carries, so it works locally without a login.
    dashboard_demo_key: str | None = None

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if environ is None else environ

        database_url = env.get("DATABASE_URL", "").strip()
        if not database_url:
            raise ConfigError("DATABASE_URL is required")

        log_level = env.get("LOG_LEVEL", "INFO").strip().upper()
        if log_level not in LOG_LEVELS:
            raise ConfigError(f"LOG_LEVEL must be one of {', '.join(LOG_LEVELS)}")

        api_keys = _api_keys(env)
        return cls(
            database_url=database_url,
            log_level=log_level,
            api_keys=api_keys,
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
            summary_retention=timedelta(
                days=_positive_int(env, "SUMMARY_RETENTION_DAYS", DEFAULT_SUMMARY_RETENTION.days)
            ),
            retention_batch_size=_positive_int(
                env, "RETENTION_BATCH_SIZE", DEFAULT_RETENTION_BATCH_SIZE
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
            scoring_stale_after=timedelta(
                seconds=_positive_int(
                    env,
                    "SCORING_STALE_AFTER_SECONDS",
                    int(DEFAULT_SCORING_STALE_AFTER.total_seconds()),
                )
            ),
            scoring=_scoring(env),
            dashboard_demo_key=_dashboard_demo_key(env, api_keys),
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
    flag_threshold = _score(env, "FLAG_THRESHOLD", DEFAULT_SCORING.flag_threshold)
    clear_threshold = _score(env, "CLEAR_THRESHOLD", DEFAULT_SCORING.clear_threshold)
    # A Clear Threshold below the Flag Threshold would clear Stations that are still flagged.
    if clear_threshold < flag_threshold:
        raise ConfigError("CLEAR_THRESHOLD must be at least FLAG_THRESHOLD")
    return ScoringConfig(
        latency_good_ms=latency_good_ms,
        latency_bad_ms=latency_bad_ms,
        error_limit=error_limit,
        latency_weight=latency_weight,
        error_weight=error_weight,
        flag_threshold=flag_threshold,
        clear_threshold=clear_threshold,
        min_reports_to_clear=_positive_int(
            env, "MIN_REPORTS_TO_CLEAR", DEFAULT_SCORING.min_reports_to_clear
        ),
    )


def _api_keys(env: Mapping[str, str]) -> dict[str, frozenset[Role]]:
    roles_by_key: dict[str, set[Role]] = {}
    for role, variable in API_KEY_VARIABLES.items():
        for key in env.get(variable, "").split(","):
            if key.strip():
                roles_by_key.setdefault(key.strip(), set()).add(role)
    return {key: frozenset(roles) for key, roles in roles_by_key.items()}


def _dashboard_demo_key(
    env: Mapping[str, str], api_keys: Mapping[str, frozenset[Role]]
) -> str | None:
    """The key is served to anyone who opens the page, so it may grant nothing beyond read."""
    key = env.get("DASHBOARD_DEMO_KEY", "").strip()
    if not key:
        return None
    if key not in api_keys:
        raise ConfigError("DASHBOARD_DEMO_KEY is not a configured API key")
    if api_keys[key] != {Role.READ}:
        raise ConfigError("DASHBOARD_DEMO_KEY must have only the 'read' role")
    return key


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


def _score(env: Mapping[str, str], name: str, default: int) -> int:
    """A Hygiene Score threshold: an integer from 0 to 100."""
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be an integer from 0 to 100") from None
    if not 0 <= value <= 100:
        raise ConfigError(f"{name} must be an integer from 0 to 100")
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
