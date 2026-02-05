"""add user boolean columns

Revision ID: add_user_boolean_columns
Revises: add_oauth_connected_app
Create Date: 2026-01-25 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_user_boolean_columns'
down_revision: Union[str, Sequence[str], None] = 'add_oauth_connected_app'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add missing boolean columns to users table
    # Check if columns already exist to make migration idempotent
    from sqlalchemy import text
    
    # Check if is_active column exists
    result = op.get_bind().execute(text("""
        SELECT EXISTS (
            SELECT FROM information_schema.columns 
            WHERE table_schema = 'public' 
            AND table_name = 'users' 
            AND column_name = 'is_active'
        );
    """))
    is_active_exists = result.scalar()
    
    if not is_active_exists:
        op.add_column('users', sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')))
    
    # Check if is_superuser column exists
    result = op.get_bind().execute(text("""
        SELECT EXISTS (
            SELECT FROM information_schema.columns 
            WHERE table_schema = 'public' 
            AND table_name = 'users' 
            AND column_name = 'is_superuser'
        );
    """))
    is_superuser_exists = result.scalar()
    
    if not is_superuser_exists:
        op.add_column('users', sa.Column('is_superuser', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    
    # Check if is_verified column exists
    result = op.get_bind().execute(text("""
        SELECT EXISTS (
            SELECT FROM information_schema.columns 
            WHERE table_schema = 'public' 
            AND table_name = 'users' 
            AND column_name = 'is_verified'
        );
    """))
    is_verified_exists = result.scalar()
    
    if not is_verified_exists:
        op.add_column('users', sa.Column('is_verified', sa.Boolean(), nullable=False, server_default=sa.text('false')))


def downgrade() -> None:
    """Downgrade schema."""
    # Remove the boolean columns
    op.drop_column('users', 'is_verified')
    op.drop_column('users', 'is_superuser')
    op.drop_column('users', 'is_active')
