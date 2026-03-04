"""add_email_drafting_columns_to_users

Revision ID: 0a4805f3b072
Revises: e351735a137b
Create Date: 2026-01-27 21:34:33.735197

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0a4805f3b072'
down_revision: Union[str, None] = 'e351735a137b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add email drafting columns to users table
    # Use IF NOT EXISTS pattern for PostgreSQL compatibility
    conn = op.get_bind()
    
    # Check if columns exist
    result = conn.execute(sa.text("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name='users' AND column_name='email_drafting_enabled'
    """))
    if not result.fetchone():
        op.add_column('users', sa.Column('email_drafting_enabled', sa.Boolean(), nullable=False, server_default='false'))
    
    result = conn.execute(sa.text("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name='users' AND column_name='email_drafting_enabled_at'
    """))
    if not result.fetchone():
        op.add_column('users', sa.Column('email_drafting_enabled_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    # Remove email drafting columns from users table
    op.drop_column('users', 'email_drafting_enabled_at')
    op.drop_column('users', 'email_drafting_enabled')
