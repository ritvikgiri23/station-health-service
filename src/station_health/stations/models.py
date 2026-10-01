from datetime import datetime

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from station_health.db_types import UtcDateTime
from station_health.extensions import Base


class Station(Base):
    """An entry in the Station Registry."""

    __tablename__ = "stations"

    station_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    region: Mapped[str | None] = mapped_column(String(64))
    # False for an Unverified Station: registered automatically by its first Health Report.
    verified: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime)
