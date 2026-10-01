from datetime import datetime
from enum import StrEnum

from sqlalchemy import Enum, Index, String
from sqlalchemy.dialects.mysql import DOUBLE, INTEGER
from sqlalchemy.orm import Mapped, mapped_column

from station_health.db_types import UtcDateTime
from station_health.extensions import Base

ERROR_COUNT_MAX = 2**32 - 1  # INT UNSIGNED


class ConnectivityStatus(StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"


class HealthReport(Base):
    """The result of one Collector Probe of one Station.

    The primary key (`station_id`, `timestamp`) makes ingest idempotent and keeps the
    table partition-ready. There is deliberately no foreign key to Station: MySQL
    partitioned tables cannot have one (ADR-0001).
    """

    __tablename__ = "health_reports"
    __table_args__ = (Index("ix_health_reports_timestamp", "timestamp"),)

    station_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(UtcDateTime, primary_key=True)
    connectivity_status: Mapped[ConnectivityStatus] = mapped_column(
        Enum(
            ConnectivityStatus,
            name="connectivity_status",
            values_callable=lambda statuses: [s.value for s in statuses],
        )
    )
    latency_ms: Mapped[float] = mapped_column(DOUBLE(asdecimal=False))
    # Errors since the Station's previous Health Report, not a running total.
    error_count: Mapped[int] = mapped_column(INTEGER(unsigned=True))
    firmware_version: Mapped[str] = mapped_column(String(64))
    received_at: Mapped[datetime] = mapped_column(UtcDateTime)
