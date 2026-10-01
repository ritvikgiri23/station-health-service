"""`python -m station_health.simulator`: play the Collector for a fleet of Stations.

Every option can also be set by the environment variable shown in its help. Runs until
SIGTERM or SIGINT, or until --minutes simulated minutes have been sent.
"""

import argparse
import os
import signal
import threading
from datetime import timedelta

from station_health.clock import system_clock
from station_health.log import configure_logging
from station_health.simulator.live import HttpApi, run_live
from station_health.simulator.profiles import fleet


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    configure_logging(os.environ.get("LOG_LEVEL", "INFO").upper())
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    run_live(
        HttpApi(args.api_url, args.ingest_key, args.admin_key),
        fleet(args.stations),
        speed=args.speed,
        backlog=timedelta(minutes=args.backlog_minutes),
        clock=system_clock,
        sleep=stop.wait,
        stop_after_minutes=args.minutes,
        stop=stop,
        seed=args.seed,
    )


def _parser() -> argparse.ArgumentParser:
    # Defaults from the environment are strings, so argparse validates them like flags.
    env = os.environ
    parser = argparse.ArgumentParser(
        prog="python -m station_health.simulator",
        description="Play the Collector for a fleet of Stations with scenario profiles.",
    )
    parser.add_argument(
        "--api-url",
        default=env.get("SIM_API_URL", "http://localhost:8000"),
        help="The service's base URL (SIM_API_URL). Default: http://localhost:8000.",
    )
    parser.add_argument(
        "--ingest-key",
        default=env.get("SIM_INGEST_KEY", "dev-ingest-key"),
        help="Key with the ingest role, to send Health Reports (SIM_INGEST_KEY).",
    )
    parser.add_argument(
        "--admin-key",
        default=env.get("SIM_ADMIN_KEY", "dev-admin-key"),
        help="Key with the admin role, to register the fleet's Stations (SIM_ADMIN_KEY).",
    )
    parser.add_argument(
        "--stations",
        type=_positive_int,
        default=env.get("SIM_STATIONS", "50"),
        help="Stations to simulate; profiles are assigned in turn (SIM_STATIONS). Default: 50.",
    )
    parser.add_argument(
        "--speed",
        type=_speed,
        default=env.get("SIM_SPEED", "60"),
        help="Simulated minutes per real minute while replaying the backlog; above 1, or it "
        "never catches up (SIM_SPEED). Default: 60.",
    )
    parser.add_argument(
        "--backlog-minutes",
        type=_positive_int,
        default=env.get("SIM_BACKLOG_MINUTES", "30"),
        help="How far in the past simulated time starts (SIM_BACKLOG_MINUTES). Default: 30.",
    )
    parser.add_argument(
        "--minutes",
        type=_positive_int,
        default=None,
        help="Stop after this many simulated minutes. Default: run until stopped.",
    )
    parser.add_argument(
        "--seed", type=int, default=1, help="Random seed for the readings. Default: 1."
    )
    return parser


def _positive_int(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{raw!r} is not a positive integer") from None
    if value <= 0:
        raise argparse.ArgumentTypeError(f"{raw!r} is not a positive integer")
    return value


def _speed(raw: str) -> float:
    try:
        value = float(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{raw!r} is not a number above 1") from None
    if not 1 < value < float("inf"):
        raise argparse.ArgumentTypeError(f"{raw!r} is not a number above 1")
    return value


if __name__ == "__main__":
    main()
