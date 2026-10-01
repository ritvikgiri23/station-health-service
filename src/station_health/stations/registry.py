"""Station Registry storage."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, exists, select
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.engine import CursorResult

from station_health.extensions import db
from station_health.health.models import StationHealth
from station_health.paging import InvalidCursor, decode_cursor, encode_cursor
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


def register_station(station_id: str, region: str | None, now: datetime) -> tuple[Station, bool]:
    """Register or update a Station with its Region and mark it verified. Commits.

    Idempotent. Returns the Station and whether it was new to the Station Registry. Two
    concurrent first registrations of one Station both report it as new.
    """
    created = find_station(station_id) is None
    register_stations({station_id: region}, now)
    station = db.session.get(Station, station_id, populate_existing=True)
    assert station is not None
    return station, created


def register_stations(region_by_station_id: dict[str, str | None], now: datetime) -> None:
    """Register or update each Station with its Region, all verified, in one statement. Commits."""
    statement = insert(Station).values(
        [
            {
                "station_id": station_id,
                "region": region,
                "verified": True,
                "created_at": now,
                "updated_at": now,
            }
            for station_id, region in region_by_station_id.items()
        ]
    )
    db.session.execute(
        statement.on_duplicate_key_update(
            region=statement.inserted.region, verified=True, updated_at=now
        )
    )
    db.session.commit()


def delete_station(station_id: str) -> bool:
    """Remove a Station from the Station Registry, with its Station health. Commits.

    Returns False if it was not registered. Its Health Reports and Flag Changes stay, and
    age out or remain as history. Without its Station health, a Station registered again
    later is assessed afresh, not from its old flag state.
    """
    result = db.session.execute(delete(Station).where(Station.station_id == station_id))
    assert isinstance(result, CursorResult)
    db.session.execute(delete(StationHealth).where(StationHealth.station_id == station_id))
    db.session.commit()
    return result.rowcount > 0


def find_station(station_id: str) -> Station | None:
    return db.session.get(Station, station_id)


@dataclass(frozen=True)
class StationPage:
    items: list[Station]
    # None on the last page.
    next_cursor: str | None


def list_stations(verified: bool | None, limit: int, cursor: str | None) -> StationPage:
    """One page of the Station Registry by `station_id`, optionally only (un)verified.

    Raises InvalidCursor for a malformed cursor.
    """
    statement = select(Station).order_by(Station.station_id).limit(limit + 1)
    if verified is not None:
        statement = statement.where(Station.verified.is_(verified))
    if cursor is not None:
        after = decode_cursor(cursor).get("station_id")
        if not isinstance(after, str):
            raise InvalidCursor
        statement = statement.where(Station.station_id > after)
    stations = list(db.session.scalars(statement))
    items = stations[:limit]
    more = len(stations) > limit
    return StationPage(
        items=items,
        next_cursor=encode_cursor({"station_id": items[-1].station_id}) if more else None,
    )
