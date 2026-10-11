"""ticket fare category, distance and stage (BMTC stage fare table)

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("access_tickets", sa.Column("fare_category", sa.String(length=10), nullable=False, server_default="ADULT"))
    op.add_column("access_tickets", sa.Column("distance_km", sa.Float(), nullable=True))
    op.add_column("access_tickets", sa.Column("fare_stage", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("access_tickets", "fare_stage")
    op.drop_column("access_tickets", "distance_km")
    op.drop_column("access_tickets", "fare_category")
