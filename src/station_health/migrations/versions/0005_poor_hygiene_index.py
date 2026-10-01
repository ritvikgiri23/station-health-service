"""Index Station health for the Poor Hygiene list.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-01

"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    # The list reads only rows with Poor Hygiene, and can sort them by "flagged since".
    op.create_index(
        "ix_station_health_poor_hygiene_flagged_since",
        "station_health",
        ["poor_hygiene", "flagged_since"],
    )


def downgrade():
    op.drop_index("ix_station_health_poor_hygiene_flagged_since", table_name="station_health")
