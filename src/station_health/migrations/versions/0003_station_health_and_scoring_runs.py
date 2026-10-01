"""Station health (current Hygiene Score per Station) and the scoring-run record.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-01

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "station_health",
        sa.Column("station_id", sa.String(64), primary_key=True),
        sa.Column("hygiene_score", sa.SmallInteger(), nullable=False),
        sa.Column("availability", mysql.DOUBLE(asdecimal=False), nullable=False),
        sa.Column("latency_score", mysql.DOUBLE(asdecimal=False), nullable=True),
        sa.Column("error_score", mysql.DOUBLE(asdecimal=False), nullable=True),
        sa.Column("p95_latency_ms", mysql.DOUBLE(asdecimal=False), nullable=True),
        sa.Column("report_count", mysql.INTEGER(unsigned=True), nullable=False),
    )
    op.create_table(
        "scoring_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("scored_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("stations_scored", mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column("duration_ms", mysql.DOUBLE(asdecimal=False), nullable=False),
    )


def downgrade():
    op.drop_table("scoring_runs")
    op.drop_table("station_health")
