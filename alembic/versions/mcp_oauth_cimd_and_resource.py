"""MCP OAuth: resource column on auth tables + CIMD metadata cache

Revision ID: mcp_oauth_cimd_resource
Revises: add_mcp_tables
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "mcp_oauth_cimd_resource"
down_revision: Union[str, Sequence[str], None] = "add_mcp_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "mcp_oauth_pending_authorizations",
        sa.Column("resource", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "mcp_oauth_authorization_codes",
        sa.Column("resource", sa.Text(), nullable=False, server_default=""),
    )
    op.alter_column("mcp_oauth_pending_authorizations", "resource", server_default=None)
    op.alter_column("mcp_oauth_authorization_codes", "resource", server_default=None)

    op.create_table(
        "mcp_oauth_cimd_cache",
        sa.Column("client_id_url", sa.Text(), nullable=False),
        sa.Column("document_json", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("client_id_url"),
    )


def downgrade() -> None:
    op.drop_table("mcp_oauth_cimd_cache")
    op.drop_column("mcp_oauth_authorization_codes", "resource")
    op.drop_column("mcp_oauth_pending_authorizations", "resource")
