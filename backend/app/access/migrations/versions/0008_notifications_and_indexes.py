"""in-app notifications; indexes for live trips, dashboards and college queues

Revision ID: 0008
Revises: 0007
"""
from alembic import op
import sqlalchemy as sa


revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

INDEXES = [
    ("ix_access_tickets_trip_status", "access_tickets", ["trip_id", "status"]),
    ("ix_access_tickets_status_issued", "access_tickets", ["status", "issued_at"]),
    ("ix_access_trips_status", "access_trips", ["status"]),
    ("ix_access_student_passes_status_expiry", "access_student_passes", ["status", "expiry_date"]),
    ("ix_access_student_verifications_college_status", "access_student_verifications", ["college_id", "status"]),
    ("ix_access_ticket_verifications_conductor_created", "access_ticket_verifications", ["conductor_id", "created_at"]),
    ("ix_access_buses_route", "access_buses", ["route"]),
]


def upgrade() -> None:
    op.create_table(
        "access_notifications",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("user_id", sa.String(length=32), sa.ForeignKey("access_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=140), nullable=False),
        sa.Column("body", sa.String(length=400), nullable=False),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("dedupe_key", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("user_id", "dedupe_key", name="uq_access_notifications_dedupe"),
    )
    op.create_index("ix_access_notifications_user_created", "access_notifications", ["user_id", "created_at"])
    for name, table, cols in INDEXES:
        op.create_index(name, table, cols)


def downgrade() -> None:
    for name, table, _ in INDEXES:
        op.drop_index(name, table_name=table)
    op.drop_index("ix_access_notifications_user_created", table_name="access_notifications")
    op.drop_table("access_notifications")
