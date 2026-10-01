from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, Boolean, Enum, Index, Integer, SmallInteger, String
from sqlalchemy.dialects.mysql import DOUBLE, INTEGER
from sqlalchemy.orm import Mapped, mapped_column

from station_health.db_types import UtcDateTime
from station_health.extensions import Base
from station_health.scoring import FlagDirection, FlagReason


def _values_enum(enum: type[StrEnum], name: str) -> Enum:
    """A MySQL ENUM of the members' values rather than their names."""
    return Enum(enum, name=name, values_callable=lambda members: [m.value for m in members])


class StationHealth(Base):
    """A Station's current Hygiene Score, its parts and its flag state.

    One row per Station. A scoring run writes a row only when its Hygiene Score, Silent,
    Poor Hygiene, Flag Reason or firmware version changed, so the other parts are as of that
    write, and freshness comes from the scoring-run record, never from this table (ADR-0003).
    """

    __tablename__ = "station_health"
    # For the Poor Hygiene list.
    __table_args__ = (
        Index("ix_station_health_poor_hygiene_flagged_since", "poor_hygiene", "flagged_since"),
    )

    station_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # Null, like every part of the score, while the Station is Silent.
    hygiene_score: Mapped[int | None] = mapped_column(SmallInteger)
    availability: Mapped[float | None] = mapped_column(DOUBLE(asdecimal=False))
    # Null when the window held no online Health Reports, so latency and errors went unmeasured.
    latency_score: Mapped[float | None] = mapped_column(DOUBLE(asdecimal=False))
    error_score: Mapped[float | None] = mapped_column(DOUBLE(asdecimal=False))
    p95_latency_ms: Mapped[float | None] = mapped_column(DOUBLE(asdecimal=False))
    report_count: Mapped[int] = mapped_column(INTEGER(unsigned=True))
    silent: Mapped[bool] = mapped_column(Boolean)
    poor_hygiene: Mapped[bool] = mapped_column(Boolean)
    # Both null unless the Station has Poor Hygiene.
    flag_reason: Mapped[FlagReason | None] = mapped_column(_values_enum(FlagReason, "flag_reason"))
    flagged_since: Mapped[datetime | None] = mapped_column(UtcDateTime)
    # From the newest Health Report in the Scoring Window. Kept while Silent; null until
    # a scoring run has seen a Health Report for the Station.
    firmware_version: Mapped[str | None] = mapped_column(String(64))


class FlagChangeRecord(Base):
    """A Flag Change: a Station entering or leaving Poor Hygiene. Append-only.

    `id` orders the log. Leaving records the Flag Reason the Station had while flagged.
    """

    __tablename__ = "flag_changes"
    __table_args__ = (Index("ix_flag_changes_station_id_changed_at", "station_id", "changed_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    station_id: Mapped[str] = mapped_column(String(64))
    changed_at: Mapped[datetime] = mapped_column(UtcDateTime)
    direction: Mapped[FlagDirection] = mapped_column(_values_enum(FlagDirection, "direction"))
    flag_reason: Mapped[FlagReason] = mapped_column(_values_enum(FlagReason, "flag_reason"))
    # The Hygiene Score at the time; null for a Silent Station.
    hygiene_score: Mapped[int | None] = mapped_column(SmallInteger)


SCORING_RUN_RECORD_ID = 1


class ScoringRunRecord(Base):
    """The last completed scoring run. A single row, with id `SCORING_RUN_RECORD_ID`."""

    __tablename__ = "scoring_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    scored_at: Mapped[datetime] = mapped_column(UtcDateTime)
    stations_scored: Mapped[int] = mapped_column(INTEGER(unsigned=True))
    duration_ms: Mapped[float] = mapped_column(DOUBLE(asdecimal=False))
