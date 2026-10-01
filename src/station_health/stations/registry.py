"""Station Registry storage."""

from datetime import datetime

from sqlalchemy import exists, select
from sqlalchemy.dialects.mysql import insert

from station_health.extensions import db
from station_health.stations.models import Station


def register_unverified_station(station_id: str, now: datetime) -> None:
    """Add `station_id` as an Unverified Station with no Region, unless it is already registered.

    Runs in the caller's transaction and does not commit. The common case, an already
    registered Station, is a plain read that takes no lock on the Station row.
    """
    if db.session.scalar(select(exists().where(Station.station_id == station_id))):
        return
    statement = insert(Station).values(
        station_id=station_id, region=None, verified=False, created_at=now, updated_at=now
    )
    db.session.execute(statement.on_duplicate_key_update(station_id=statement.inserted.station_id))


def find_station(station_id: str) -> Station | None:
    return db.session.get(Station, station_id)
