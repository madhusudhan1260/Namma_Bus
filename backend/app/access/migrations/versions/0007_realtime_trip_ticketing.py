"""realtime trip ticketing: trip passenger counter + capacity, ticket ↔ trip, idempotency, payment orders

Revision ID: 0007
Revises: 0006
"""
from alembic import op
import sqlalchemy as sa


revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("access_buses", sa.Column("max_capacity", sa.Integer(), nullable=False, server_default="50"))

    op.add_column("access_trips", sa.Column("trip_code", sa.String(length=40), nullable=True))
    op.add_column("access_trips", sa.Column("passenger_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("access_trips", sa.Column("tickets_issued", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("access_trips", sa.Column("max_capacity", sa.Integer(), nullable=False, server_default="50"))
    op.add_column("access_trips", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    op.create_unique_constraint("uq_access_trips_trip_code", "access_trips", ["trip_code"])
    # Close any duplicate ACTIVE trips per bus left from before, then enforce one ACTIVE trip per bus
    op.execute("""
        UPDATE access_trips t SET status = 'COMPLETED', ended_at = now()
        WHERE status = 'ACTIVE' AND bus_id IS NOT NULL AND id NOT IN (
            SELECT DISTINCT ON (bus_id) id FROM access_trips WHERE status = 'ACTIVE' AND bus_id IS NOT NULL ORDER BY bus_id, started_at DESC
        )
    """)
    op.create_index("uq_access_trips_one_active_per_bus", "access_trips", ["bus_id"], unique=True, postgresql_where=sa.text("status = 'ACTIVE'"))

    op.add_column("access_tickets", sa.Column("trip_id", sa.String(length=32), sa.ForeignKey("access_trips.id"), nullable=True))
    op.create_index("ix_access_tickets_trip_id", "access_tickets", ["trip_id"])
    op.add_column("access_tickets", sa.Column("bus_id", sa.String(length=32), sa.ForeignKey("access_buses.id"), nullable=True))
    op.add_column("access_tickets", sa.Column("issued_by", sa.String(length=32), nullable=True))
    op.add_column("access_tickets", sa.Column("idempotency_key", sa.String(length=64), nullable=True))
    op.add_column("access_tickets", sa.Column("payment_provider", sa.String(length=20), nullable=True))
    op.add_column("access_tickets", sa.Column("payment_order_id", sa.String(length=64), nullable=True))
    op.create_index("ix_access_tickets_payment_order_id", "access_tickets", ["payment_order_id"])
    op.add_column("access_tickets", sa.Column("payment_reference", sa.String(length=64), nullable=True))
    op.add_column("access_tickets", sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("uq_access_tickets_idempotency", "access_tickets", ["user_id", "idempotency_key"], unique=True,
                    postgresql_where=sa.text("idempotency_key IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("uq_access_tickets_idempotency", table_name="access_tickets")
    for col in ("issued_at", "payment_reference", "payment_order_id", "payment_provider", "idempotency_key", "issued_by", "bus_id", "trip_id"):
        if col == "payment_order_id":
            op.drop_index("ix_access_tickets_payment_order_id", table_name="access_tickets")
        if col == "trip_id":
            op.drop_index("ix_access_tickets_trip_id", table_name="access_tickets")
        op.drop_column("access_tickets", col)
    op.drop_index("uq_access_trips_one_active_per_bus", table_name="access_trips")
    op.drop_constraint("uq_access_trips_trip_code", "access_trips", type_="unique")
    for col in ("updated_at", "max_capacity", "tickets_issued", "passenger_count", "trip_code"):
        op.drop_column("access_trips", col)
    op.drop_column("access_buses", "max_capacity")
