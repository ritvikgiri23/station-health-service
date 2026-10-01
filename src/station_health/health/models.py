from datetime import datetime

from sqlalchemy import Integer, SmallInteger, String
from sqlalchemy.dialects.mysql import DOUBLE, INTEGER
from sqlalchemy.orm import Mapped, mapped_column

from station_health.db_types import UtcDateTime
from station_health.extensions import Base


class StationHealth(Base):
    """A Station's current Hygiene Score and its parts, as of the last scoring run that scored it.

    One row per Station. Rows are not touched when unchanged, so freshness comes from the
    scoring-run record, never from this table (ADR-0003).
    """

    __tablename__ = "station_health"

    station_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    hygiene_score: Mapped[int] = mapped_column(SmallInteger)
    availability: Mapped[float] = mapped_column(DOUBLE(asdecimal=False))
    # Null when the window held no online Health Reports, so latency and errors went unmeasured.
    latency_score: Mapped[float | None] = mapped_column(DOUBLE(asdecimal=False))
    error_score: Mapped[float | None] = mapped_column(DOUBLE(asdecimal=False))
    p95_latency_ms: Mapped[float | None] = mapped_column(DOUBLE(asdecimal=False))
    report_count: Mapped[int] = mapped_column(INTEGER(unsigned=True))


SCORING_RUN_RECORD_ID = 1


class ScoringRunRecord(Base):
    """The last completed scoring run. A single row, with id `SCORING_RUN_RECORD_ID`."""

    __tablename__ = "scoring_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    scored_at: Mapped[datetime] = mapped_column(UtcDateTime)
    stations_scored: Mapped[int] = mapped_column(INTEGER(unsigned=True))
    duration_ms: Mapped[float] = mapped_column(DOUBLE(asdecimal=False))
