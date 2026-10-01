"""Latest firmware version on Station health, for the metrics snapshot.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-01

"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    # Null until a scoring run has seen a Health Report for the Station.
    op.add_column("station_health", sa.Column("firmware_version", sa.String(64), nullable=True))


def downgrade():
    op.drop_column("station_health", "firmware_version")
