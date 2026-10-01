"""Poor Hygiene, Silent and Flag Reason on Station health, and the Flag Change log.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-01

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

FLAG_REASONS = ("silent", "availability", "latency", "errors")


def upgrade():
    # A Silent Station has no Hygiene Score or Availability.
    op.alter_column(
        "station_health", "hygiene_score", existing_type=sa.SmallInteger(), nullable=True
    )
    op.alter_column(
        "station_health", "availability", existing_type=mysql.DOUBLE(asdecimal=False), nullable=True
    )
    op.add_column(
        "station_health",
        sa.Column("silent", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "station_health",
        sa.Column("poor_hygiene", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "station_health",
        sa.Column("flag_reason", sa.Enum(*FLAG_REASONS, name="flag_reason"), nullable=True),
    )
    op.add_column(
        "station_health", sa.Column("flagged_since", mysql.DATETIME(fsp=6), nullable=True)
    )
    op.create_table(
        "flag_changes",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("station_id", sa.String(64), nullable=False),
        sa.Column("changed_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("direction", sa.Enum("entered", "left", name="direction"), nullable=False),
        sa.Column("flag_reason", sa.Enum(*FLAG_REASONS, name="flag_reason"), nullable=False),
        sa.Column("hygiene_score", sa.SmallInteger(), nullable=True),
    )
    op.create_index(
        "ix_flag_changes_station_id_changed_at", "flag_changes", ["station_id", "changed_at"]
    )


def downgrade():
    op.drop_table("flag_changes")
    op.drop_column("station_health", "flagged_since")
    op.drop_column("station_health", "flag_reason")
    op.drop_column("station_health", "poor_hygiene")
    op.drop_column("station_health", "silent")
    # Silent rows have no score to restore.
    op.execute("DELETE FROM station_health WHERE hygiene_score IS NULL")
    op.alter_column(
        "station_health", "availability", existing_type=mysql.DOUBLE(asdecimal=False), nullable=False
    )
    op.alter_column(
        "station_health", "hygiene_score", existing_type=sa.SmallInteger(), nullable=False
    )
