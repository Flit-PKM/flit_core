"""Add MCP OAuth, API keys, and authorization tables

Revision ID: add_mcp_tables
Revises: notesearch_renormalize_unicode
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "add_mcp_tables"
down_revision: Union[str, Sequence[str], None] = "notesearch_renormalize_unicode"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mcp_refresh_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("token", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("scopes", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_mcp_refresh_tokens_token"),
        "mcp_refresh_tokens",
        ["token"],
        unique=True,
    )

    op.create_table(
        "mcp_access_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("scopes", sa.String(length=255), nullable=False),
        sa.Column("jti", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("refresh_token_id", sa.Integer(), nullable=True),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["refresh_token_id"],
            ["mcp_refresh_tokens.id"],
            ondelete="SET NULL",
            use_alter=True,
            name=op.f("fk_mcp_access_tokens_refresh_token_id_mcp_refresh_tokens"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_mcp_access_tokens_jti"),
        "mcp_access_tokens",
        ["jti"],
        unique=True,
    )
    op.create_index(
        op.f("ix_mcp_access_tokens_token"),
        "mcp_access_tokens",
        ["token"],
        unique=True,
    )

    op.create_table(
        "mcp_api_keys",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("key_hash", sa.String(length=255), nullable=False),
        sa.Column("key_prefix", sa.String(length=32), nullable=False),
        sa.Column("scopes", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_mcp_api_keys_key_prefix"),
        "mcp_api_keys",
        ["key_prefix"],
        unique=False,
    )

    op.create_table(
        "mcp_oauth_authorization_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("client_id", sa.String(length=512), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("scopes", sa.String(length=255), nullable=False),
        sa.Column("code_challenge", sa.String(length=128), nullable=False),
        sa.Column("code_challenge_method", sa.String(length=16), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_mcp_oauth_authorization_codes_code"),
        "mcp_oauth_authorization_codes",
        ["code"],
        unique=True,
    )

    op.create_table(
        "mcp_oauth_pending_authorizations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=128), nullable=False),
        sa.Column("client_id", sa.String(length=512), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("scopes", sa.String(length=255), nullable=False),
        sa.Column("code_challenge", sa.String(length=128), nullable=False),
        sa.Column("code_challenge_method", sa.String(length=16), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_mcp_oauth_pending_authorizations_state"),
        "mcp_oauth_pending_authorizations",
        ["state"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("mcp_oauth_pending_authorizations")
    op.drop_table("mcp_oauth_authorization_codes")
    op.drop_table("mcp_api_keys")
    op.drop_table("mcp_access_tokens")
    op.drop_table("mcp_refresh_tokens")  # after access_tokens (FK from access)

