"""Station Registry and raw Health Reports.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-01

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "stations",
        sa.Column("station_id", sa.String(64), primary_key=True),
        sa.Column("region", sa.String(64), nullable=True),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("updated_at", mysql.DATETIME(fsp=6), nullable=False),
    )
    # No foreign key to stations, and the timestamp is in the primary key, so the
    # table can be range-partitioned by timestamp later (ADR-0001).
    op.create_table(
        "health_reports",
        sa.Column("station_id", sa.String(64), nullable=False),
        sa.Column("timestamp", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column(
            "connectivity_status",
            sa.Enum("online", "offline", name="connectivity_status"),
            nullable=False,
        ),
        sa.Column("latency_ms", mysql.DOUBLE(asdecimal=False), nullable=False),
        sa.Column("error_count", mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column("firmware_version", sa.String(64), nullable=False),
        sa.Column("received_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.PrimaryKeyConstraint("station_id", "timestamp"),
    )
    op.create_index("ix_health_reports_timestamp", "health_reports", ["timestamp"])


def downgrade():
    op.drop_table("health_reports")
    op.drop_table("stations")
