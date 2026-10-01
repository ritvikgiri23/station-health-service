"""`flask seed-stations`: load a Station Registry with Stations spread across Regions."""

import click
from flask.cli import with_appcontext

from station_health.runtime import current_time
from station_health.stations.registry import register_stations

SEED_REGIONS = ("us-west", "us-east", "eu-west", "eu-central", "ap-southeast")
BATCH_SIZE = 1000


def seed_station_id(number: int) -> str:
    return f"ST-{number:06d}"


@click.command("seed-stations")
@click.option(
    "--count",
    type=click.IntRange(min=1, max=999_999),
    default=1000,
    show_default=True,
    help="Stations to register.",
)
@with_appcontext
def seed_stations(count: int) -> None:
    """Register ST-000001 to ST-<count>, verified, with Regions assigned in turn.

    Idempotent: re-running updates the same Stations and confirms any that were
    Unverified Stations.
    """
    now = current_time()
    for start in range(1, count + 1, BATCH_SIZE):
        numbers = range(start, min(start + BATCH_SIZE, count + 1))
        register_stations(
            {seed_station_id(n): SEED_REGIONS[(n - 1) % len(SEED_REGIONS)] for n in numbers}, now
        )
    click.echo(f"Seeded {count} Stations across {min(count, len(SEED_REGIONS))} Regions.")
