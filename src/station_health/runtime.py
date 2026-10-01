"""Access to the current app's settings and clock from request or app context."""

from datetime import datetime

from flask import Flask, current_app

from station_health.clock import Clock
from station_health.config import Settings

_SETTINGS = "station_health.settings"
_CLOCK = "station_health.clock"


def install(app: Flask, settings: Settings, clock: Clock) -> None:
    app.extensions[_SETTINGS] = settings
    app.extensions[_CLOCK] = clock


def current_settings() -> Settings:
    settings: Settings = current_app.extensions[_SETTINGS]
    return settings


def current_time() -> datetime:
    clock: Clock = current_app.extensions[_CLOCK]
    return clock()
