"""Shared test helpers: a controllable clock, API keys, and Health Report payloads."""

import threading
from datetime import UTC, datetime, timedelta
from typing import Any

INGEST_KEY = "test-ingest-key"
READ_KEY = "test-read-key"
ADMIN_KEY = "test-admin-key"

TEST_API_KEYS = {
    "API_KEYS_INGEST": INGEST_KEY,
    "API_KEYS_READ": READ_KEY,
    "API_KEYS_ADMIN": ADMIN_KEY,
}

START = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)


class FakeClock:
    """A clock that only moves when a test moves it."""

    def __init__(self, now: datetime = START) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class OneCycle(threading.Event):
    """A stop event that lets the worker loop run exactly one cycle."""

    def __init__(self) -> None:
        super().__init__()
        self.checks = 0

    def is_set(self) -> bool:
        self.checks += 1
        return self.checks > 1

    def wait(self, timeout: float | None = None) -> bool:
        return True


def auth(key: str) -> dict[str, str]:
    return {"X-API-Key": key}


def health_report(**overrides: Any) -> dict[str, Any]:
    """A valid Health Report payload, timestamped one minute before START."""
    payload: dict[str, Any] = {
        "station_id": "ST-0001",
        "timestamp": iso(START - timedelta(minutes=1)),
        "connectivity_status": "online",
        "latency_ms": 120.5,
        "error_count": 0,
        "firmware_version": "1.4.2",
    }
    payload.update(overrides)
    return payload


def iso(moment: datetime) -> str:
    return moment.isoformat()
