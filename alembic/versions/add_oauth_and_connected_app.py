"""Add OAuth 2.1 and ConnectedApp models

Revision ID: add_oauth_connected_app
Revises: 69bb1a9e4bac
Create Date: 2026-01-25 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'add_oauth_connected_app'
down_revision: Union[str, Sequence[str], None] = '69bb1a9e4bac'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Check if apps table exists, create if it doesn't
    from sqlalchemy import text
    
    # Check if apps table exists
    result = op.get_bind().execute(text("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name = 'apps'
        );
    """))
    apps_exists = result.scalar()
    
    if not apps_exists:
        op.create_table(
            'apps',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(length=255), nullable=False),
            sa.Column('description', sa.Text(), nullable=False),
            sa.PrimaryKeyConstraint('id', name=op.f('pk_apps'))
        )

    # Create connected_apps table
    op.create_table(
        'connected_apps',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('app_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('client_id', sa.String(length=255), nullable=False),
        sa.Column('client_secret', sa.String(length=255), nullable=False),
        sa.Column('redirect_uris', postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['app_id'], ['apps.id'], name=op.f('fk_connected_apps_app_id_apps')),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_connected_apps_user_id_users')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_connected_apps'))
    )
    op.create_index(op.f('ix_connected_apps_client_id'), 'connected_apps', ['client_id'], unique=True)

    # Update notes.source_id foreign key from apps.id to connected_apps.id
    # Only if notes table exists
    result = op.get_bind().execute(text("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name = 'notes'
        );
    """))
    notes_exists = result.scalar()
    
    if notes_exists:
        # Get existing foreign keys on notes table that reference source_id
        result = op.get_bind().execute(text("""
            SELECT tc.constraint_name 
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu 
                ON tc.constraint_name = kcu.constraint_name
            WHERE tc.table_schema = 'public' 
            AND tc.table_name = 'notes' 
            AND tc.constraint_type = 'FOREIGN KEY'
            AND kcu.column_name = 'source_id';
        """))
        fk_constraints = [row[0] for row in result]
        
        # Drop existing foreign key constraints on source_id
        for constraint_name in fk_constraints:
            op.drop_constraint(constraint_name, 'notes', type_='foreignkey')

        # Add new foreign key to connected_apps
        # Using raw SQL for consistency
        constraint_name = op.f('fk_notes_source_id_connected_apps')
        op.execute(text(f"""
            ALTER TABLE notes
            ADD CONSTRAINT {constraint_name}
            FOREIGN KEY (source_id) REFERENCES connected_apps(id);
        """))

    # Create oauth_authorization_codes table
    op.create_table(
        'oauth_authorization_codes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=255), nullable=False),
        sa.Column('connected_app_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('code_challenge', sa.String(length=255), nullable=False),
        sa.Column('code_challenge_method', sa.String(length=10), nullable=False),
        sa.Column('redirect_uri', sa.String(length=512), nullable=False),
        sa.Column('scopes', sa.String(length=255), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('used', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['connected_app_id'], ['connected_apps.id'], name=op.f('fk_oauth_authorization_codes_connected_app_id_connected_apps')),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_oauth_authorization_codes_user_id_users')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_oauth_authorization_codes'))
    )
    op.create_index(op.f('ix_oauth_authorization_codes_code'), 'oauth_authorization_codes', ['code'], unique=True)

    # Create oauth_access_tokens table
    # Note: refresh_token_id FK will be added after oauth_refresh_tokens table is created
    op.create_table(
        'oauth_access_tokens',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('token', sa.Text(), nullable=False),
        sa.Column('connected_app_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('scopes', sa.String(length=255), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('refresh_token_id', sa.Integer(), nullable=True),
        sa.Column('revoked', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['connected_app_id'], ['connected_apps.id'], name=op.f('fk_oauth_access_tokens_connected_app_id_connected_apps')),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_oauth_access_tokens_user_id_users')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_oauth_access_tokens'))
    )
    op.create_index(op.f('ix_oauth_access_tokens_token'), 'oauth_access_tokens', ['token'], unique=True)

    # Create oauth_refresh_tokens table
    op.create_table(
        'oauth_refresh_tokens',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('token', sa.Text(), nullable=False),
        sa.Column('access_token_id', sa.Integer(), nullable=False),
        sa.Column('connected_app_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['access_token_id'], ['oauth_access_tokens.id'], name=op.f('fk_oauth_refresh_tokens_access_token_id_oauth_access_tokens')),
        sa.ForeignKeyConstraint(['connected_app_id'], ['connected_apps.id'], name=op.f('fk_oauth_refresh_tokens_connected_app_id_connected_apps')),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_oauth_refresh_tokens_user_id_users')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_oauth_refresh_tokens'))
    )
    op.create_index(op.f('ix_oauth_refresh_tokens_token'), 'oauth_refresh_tokens', ['token'], unique=True)

    # Add foreign key from oauth_access_tokens.refresh_token_id to oauth_refresh_tokens.id
    # This must be done after oauth_refresh_tokens table exists
    # Using raw SQL to avoid circular dependency issues
    constraint_name = op.f('fk_oauth_access_tokens_refresh_token_id_oauth_refresh_tokens')
    op.execute(text(f"""
        ALTER TABLE oauth_access_tokens
        ADD CONSTRAINT {constraint_name}
        FOREIGN KEY (refresh_token_id) REFERENCES oauth_refresh_tokens(id);
    """))


def downgrade() -> None:
    """Downgrade schema."""
    # Drop OAuth tables
    op.drop_index(op.f('ix_oauth_refresh_tokens_token'), table_name='oauth_refresh_tokens')
    op.drop_table('oauth_refresh_tokens')
    
    op.drop_index(op.f('ix_oauth_access_tokens_token'), table_name='oauth_access_tokens')
    op.drop_table('oauth_access_tokens')
    
    op.drop_index(op.f('ix_oauth_authorization_codes_code'), table_name='oauth_authorization_codes')
    op.drop_table('oauth_authorization_codes')

    # Restore old foreign key on notes
    op.drop_constraint(op.f('fk_notes_source_id_connected_apps'), 'notes', type_='foreignkey')
    constraint_name = op.f('fk_notes_source_id_apps')
    op.execute(text(f"""
        ALTER TABLE notes
        ADD CONSTRAINT {constraint_name}
        FOREIGN KEY (source_id) REFERENCES apps(id);
    """))

    # Drop connected_apps table
    op.drop_index(op.f('ix_connected_apps_client_id'), table_name='connected_apps')
    op.drop_table('connected_apps')

    # Note: We don't drop apps table as it might have data
