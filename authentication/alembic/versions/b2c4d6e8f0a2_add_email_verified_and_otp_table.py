"""add email_verified_at and email_verification_codes table

Revision ID: b2c4d6e8f0a2
Revises: a1b2c3d4e5f6
Create Date: 2026-03-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b2c4d6e8f0a2"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    result = conn.execute(sa.text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'email_verified_at'
    """))
    if not result.fetchone():
        op.add_column(
            "users",
            sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        )
    op.create_table(
        "email_verification_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("code", sa.String(length=10), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_email_verification_codes_email"), "email_verification_codes", ["email"], unique=False)
    op.create_index(op.f("ix_email_verification_codes_organization_id"), "email_verification_codes", ["organization_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_email_verification_codes_organization_id"), table_name="email_verification_codes")
    op.drop_index(op.f("ix_email_verification_codes_email"), table_name="email_verification_codes")
    op.drop_table("email_verification_codes")
    op.drop_column("users", "email_verified_at")
