"""add_microsoft_oauth_columns_to_users

Revision ID: a1b2c3d4e5f6
Revises: 0a4805f3b072
Create Date: 2026-02-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '0a4805f3b072'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('microsoft_id', sa.String(length=255), nullable=True))
    op.add_column('users', sa.Column('is_microsoft_user', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('users', sa.Column('microsoft_access_token', sa.Text(), nullable=True))
    op.add_column('users', sa.Column('microsoft_refresh_token', sa.Text(), nullable=True))
    op.add_column('users', sa.Column('microsoft_token_expiry', sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f('ix_users_microsoft_id'), 'users', ['microsoft_id'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_users_microsoft_id'), table_name='users')
    op.drop_column('users', 'microsoft_token_expiry')
    op.drop_column('users', 'microsoft_refresh_token')
    op.drop_column('users', 'microsoft_access_token')
    op.drop_column('users', 'is_microsoft_user')
    op.drop_column('users', 'microsoft_id')
