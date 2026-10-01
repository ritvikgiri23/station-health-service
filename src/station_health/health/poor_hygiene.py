"""The Poor Hygiene list: every Station with Poor Hygiene, worst first, cursor-paged.

Paging is by keyset: the cursor holds the sort key of a page's last Station, and the next
page starts strictly after it. Every sort ends with `station_id`, so the key is unique and,
for a fixed dataset, no Station is skipped or repeated. While scores change between
requests, a Station whose key moves across the cursor can appear twice or not at all,
but the others keep their place, which an offset could not promise.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import ColumnElement, Select, and_, func, or_, select
from sqlalchemy.orm import InstrumentedAttribute

from station_health.extensions import db
from station_health.health.models import StationHealth
from station_health.health.status import last_scored_at
from station_health.paging import DEFAULT_PAGE_SIZE, InvalidCursor, decode_cursor, encode_cursor
from station_health.scoring import FlagReason
from station_health.stations.models import Station


class PoorHygieneSort(StrEnum):
    # Worst score first, Silent (no score) as 0, then oldest "flagged since".
    SCORE = "score"
    # Oldest "flagged since" first, then worst score.
    FLAGGED_SINCE = "flagged_since"
    # Newest "flagged since" first, then worst score.
    FLAGGED_SINCE_DESC = "-flagged_since"


# The sort key's parts, by the name each has in a cursor.
_KEY_COLUMNS: dict[str, ColumnElement[Any] | InstrumentedAttribute[Any]] = {
    "score": func.coalesce(StationHealth.hygiene_score, 0),
    "flagged_since": StationHealth.flagged_since,
    "station_id": StationHealth.station_id,
}

# Each sort's key, as (part, descending). All end with `station_id`, so keys are unique.
_SORT_KEYS: dict[PoorHygieneSort, list[tuple[str, bool]]] = {
    PoorHygieneSort.SCORE: [("score", False), ("flagged_since", False), ("station_id", False)],
    PoorHygieneSort.FLAGGED_SINCE: [
        ("flagged_since", False),
        ("score", False),
        ("station_id", False),
    ],
    PoorHygieneSort.FLAGGED_SINCE_DESC: [
        ("flagged_since", True),
        ("score", False),
        ("station_id", False),
    ],
}


@dataclass(frozen=True)
class PoorHygieneFilters:
    """Each filter applies when not None."""

    region: str | None = None
    flag_reason: FlagReason | None = None
    verified: bool | None = None


@dataclass(frozen=True)
class PoorHygieneStation:
    station_id: str
    region: str | None
    verified: bool
    # None while Silent; the list sorts it as 0.
    score: int | None
    silent: bool
    flag_reason: FlagReason
    flagged_since: datetime


@dataclass(frozen=True)
class PoorHygienePage:
    items: list[PoorHygieneStation]
    # Every Station matching the filters, across all pages.
    total: int
    # None on the last page.
    next_cursor: str | None
    # When the last scoring run completed; None before the first one.
    scored_at: datetime | None


def list_poor_hygiene(
    filters: PoorHygieneFilters,
    sort: PoorHygieneSort = PoorHygieneSort.SCORE,
    limit: int = DEFAULT_PAGE_SIZE,
    cursor: str | None = None,
) -> PoorHygienePage:
    """One page of Stations with Poor Hygiene.

    Raises InvalidCursor for a cursor that is malformed or from another sort.
    """
    sort_key = _SORT_KEYS[sort]
    matching = _matching(filters)
    page = matching.order_by(
        *(
            _KEY_COLUMNS[part].desc() if descending else _KEY_COLUMNS[part]
            for part, descending in sort_key
        )
    ).limit(limit + 1)
    if cursor is not None:
        page = page.where(_after(sort_key, _decode(cursor, sort)))
    rows = db.session.execute(page).all()
    items = [PoorHygieneStation(**row._asdict()) for row in rows[:limit]]
    total = db.session.scalar(select(func.count()).select_from(matching.subquery()))
    return PoorHygienePage(
        items=items,
        total=total or 0,
        next_cursor=_encode(items[-1], sort) if len(rows) > limit else None,
        scored_at=last_scored_at(),
    )


def _matching(filters: PoorHygieneFilters) -> Select[*tuple[Any, ...]]:
    matching = (
        select(
            StationHealth.station_id,
            Station.region,
            Station.verified,
            StationHealth.hygiene_score.label("score"),
            StationHealth.silent,
            StationHealth.flag_reason,
            StationHealth.flagged_since,
        )
        .join(Station, Station.station_id == StationHealth.station_id)
        .where(StationHealth.poor_hygiene.is_(True))
    )
    if filters.region is not None:
        matching = matching.where(Station.region == filters.region)
    if filters.flag_reason is not None:
        matching = matching.where(StationHealth.flag_reason == filters.flag_reason)
    if filters.verified is not None:
        matching = matching.where(Station.verified.is_(filters.verified))
    return matching


def _after(sort_key: list[tuple[str, bool]], values: dict[str, Any]) -> ColumnElement[bool]:
    """Rows whose sort key comes strictly after `values`."""
    clauses = []
    for i, (part, descending) in enumerate(sort_key):
        ties = [_KEY_COLUMNS[earlier] == values[earlier] for earlier, _ in sort_key[:i]]
        column, value = _KEY_COLUMNS[part], values[part]
        clauses.append(and_(*ties, column < value if descending else column > value))
    return or_(*clauses)


def _encode(station: PoorHygieneStation, sort: PoorHygieneSort) -> str:
    return encode_cursor(
        {
            "sort": sort.value,
            "score": station.score or 0,
            "flagged_since": station.flagged_since.isoformat(),
            "station_id": station.station_id,
        }
    )


def _decode(cursor: str, sort: PoorHygieneSort) -> dict[str, Any]:
    decoded = decode_cursor(cursor)
    try:
        values = {
            "score": decoded["score"],
            "flagged_since": datetime.fromisoformat(decoded["flagged_since"]),
            "station_id": decoded["station_id"],
        }
    except (ValueError, TypeError, KeyError) as error:
        raise InvalidCursor from error
    valid = (
        decoded.get("sort") == sort.value
        and type(values["score"]) is int
        and isinstance(values["station_id"], str)
        and values["flagged_since"].tzinfo is not None
    )
    if not valid:
        raise InvalidCursor
    return values
