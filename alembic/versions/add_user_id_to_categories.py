"""add user_id to categories

Revision ID: add_user_id_to_categories
Revises: 9502b031fb6a
Create Date: 2026-01-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = 'add_user_id_to_categories'
down_revision: Union[str, Sequence[str], None] = '9502b031fb6a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Step 1: Add user_id column as nullable initially
    op.add_column('categories', sa.Column('user_id', sa.Integer(), nullable=True))
    
    # Step 2: Assign existing categories to the first user (if any users exist)
    # If no users exist, categories will remain NULL (edge case for fresh installs)
    op.execute(text("""
        UPDATE categories
        SET user_id = (SELECT id FROM users ORDER BY id LIMIT 1)
        WHERE user_id IS NULL
        AND EXISTS (SELECT 1 FROM users LIMIT 1)
    """))
    
    # Step 3: Make user_id NOT NULL (only if we have users, otherwise keep nullable for now)
    # In practice, if there are categories, there should be users, but we handle the edge case
    op.execute(text("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM users LIMIT 1) THEN
                ALTER TABLE categories ALTER COLUMN user_id SET NOT NULL;
            END IF;
        END $$;
    """))
    
    # Step 4: Add foreign key constraint
    op.create_foreign_key(
        op.f('fk_categories_user_id_users'),
        'categories', 'users',
        ['user_id'], ['id']
    )
    
    # Step 5: Drop the old unique index on name
    op.drop_index(op.f('ix_categories_name'), table_name='categories')
    
    # Step 6: Create composite unique constraint on (user_id, name)
    op.create_unique_constraint(
        op.f('uq_categories_user_id_name'),
        'categories',
        ['user_id', 'name']
    )
    
    # Step 7: Create index on user_id for performance
    op.create_index(
        op.f('ix_categories_user_id'),
        'categories',
        ['user_id']
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Step 1: Drop composite unique constraint
    op.drop_constraint(op.f('uq_categories_user_id_name'), 'categories', type_='unique')
    
    # Step 2: Drop index on user_id
    op.drop_index(op.f('ix_categories_user_id'), table_name='categories')
    
    # Step 3: Recreate old unique index on name
    op.create_index(op.f('ix_categories_name'), 'categories', ['name'], unique=True)
    
    # Step 4: Drop foreign key constraint
    op.drop_constraint(op.f('fk_categories_user_id_users'), 'categories', type_='foreignkey')
    
    # Step 5: Drop user_id column
    op.drop_column('categories', 'user_id')
