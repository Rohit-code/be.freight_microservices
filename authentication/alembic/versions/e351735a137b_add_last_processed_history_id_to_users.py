"""add_last_processed_history_id_to_users

Revision ID: e351735a137b
Revises: 320540b27a7f
Create Date: 2026-01-27 20:58:29.715095

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e351735a137b'
down_revision: Union[str, None] = '320540b27a7f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add last_processed_history_id column to users table (if it doesn't exist)
    conn = op.get_bind()
    
    result = conn.execute(sa.text("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name='users' AND column_name='last_processed_history_id'
    """))
    if not result.fetchone():
        op.add_column('users', sa.Column('last_processed_history_id', sa.String(length=50), nullable=True))


def downgrade() -> None:
    # Remove last_processed_history_id column from users table
    op.drop_column('users', 'last_processed_history_id')
