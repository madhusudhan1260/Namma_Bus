"""Aadhaar offline e-KYC reference photo + fingerprint, face match score

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa


revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("access_identity_verifications", sa.Column("reference_photo_document_id", sa.String(length=32), nullable=True))
    op.add_column("access_identity_verifications", sa.Column("identity_fingerprint", sa.String(length=64), nullable=True))
    op.create_index("ix_access_identity_verifications_identity_fingerprint", "access_identity_verifications", ["identity_fingerprint"])
    op.add_column("access_face_verification_attempts", sa.Column("match_score", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("access_face_verification_attempts", "match_score")
    op.drop_index("ix_access_identity_verifications_identity_fingerprint", table_name="access_identity_verifications")
    op.drop_column("access_identity_verifications", "identity_fingerprint")
    op.drop_column("access_identity_verifications", "reference_photo_document_id")
