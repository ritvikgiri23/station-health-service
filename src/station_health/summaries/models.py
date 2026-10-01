from datetime import datetime

from sqlalchemy import String
from sqlalchemy.dialects.mysql import DOUBLE, INTEGER
from sqlalchemy.orm import Mapped, mapped_column

from station_health.db_types import UtcDateTime
from station_health.extensions import Base


class HourlySummary(Base):
    """One Station's Health Reports in one completed hour, [hour_start, hour_start + 1h).

    Written once by the worker's summary catch-up, for Stations with Health Reports in the
    hour, and kept for the summary retention after the raw Health Reports are gone
    (ADR-0001). The primary key leads with `hour_start`, which the trend, the catch-up and
    retention all range over, and keeps the table partition-ready by hour.
    """

    __tablename__ = "hourly_summaries"

    hour_start: Mapped[datetime] = mapped_column(UtcDateTime, primary_key=True)
    station_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    report_count: Mapped[int] = mapped_column(INTEGER(unsigned=True))
    online_count: Mapped[int] = mapped_column(INTEGER(unsigned=True))
    # Over online Health Reports; null when none was online.
    average_latency_ms: Mapped[float | None] = mapped_column(DOUBLE(asdecimal=False))
    max_latency_ms: Mapped[float | None] = mapped_column(DOUBLE(asdecimal=False))
    p95_latency_ms: Mapped[float | None] = mapped_column(DOUBLE(asdecimal=False))
    # The hour's Error Counts added up.
    error_count_sum: Mapped[int] = mapped_column(INTEGER(unsigned=True))
    # The mean Hygiene Score of the Scoring Windows tiling the hour, a Silent one as 0.
    average_hygiene_score: Mapped[float] = mapped_column(DOUBLE(asdecimal=False))
