"""Hourly per-Station summaries.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-01

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "hourly_summaries",
        sa.Column("hour_start", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("station_id", sa.String(64), nullable=False),
        sa.Column("report_count", mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column("online_count", mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column("average_latency_ms", mysql.DOUBLE(asdecimal=False), nullable=True),
        sa.Column("max_latency_ms", mysql.DOUBLE(asdecimal=False), nullable=True),
        sa.Column("p95_latency_ms", mysql.DOUBLE(asdecimal=False), nullable=True),
        sa.Column("error_count_sum", mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column("average_hygiene_score", mysql.DOUBLE(asdecimal=False), nullable=False),
        sa.PrimaryKeyConstraint("hour_start", "station_id"),
    )


def downgrade():
    op.drop_table("hourly_summaries")
