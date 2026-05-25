"""MCP OAuth Dynamic Client Registration tables and pending-auth columns

Revision ID: mcp_oauth_dcr
Revises: mcp_oauth_cimd_resource
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "mcp_oauth_dcr"
down_revision: Union[str, Sequence[str], None] = "mcp_oauth_cimd_resource"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mcp_oauth_registered_clients",
        sa.Column("client_id", sa.String(length=128), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=True),
        sa.Column("client_name", sa.String(length=255), nullable=False),
        sa.Column("redirect_uris_json", sa.Text(), nullable=False),
        sa.Column("logo_uri", sa.Text(), nullable=True),
        sa.Column("exact_redirect_match", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("client_id"),
    )

    op.add_column(
        "mcp_oauth_pending_authorizations",
        sa.Column("client_name", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "mcp_oauth_pending_authorizations",
        sa.Column("logo_uri", sa.Text(), nullable=True),
    )
    op.add_column(
        "mcp_oauth_pending_authorizations",
        sa.Column(
            "dynamic_registration",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.alter_column(
        "mcp_oauth_pending_authorizations",
        "dynamic_registration",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_column("mcp_oauth_pending_authorizations", "dynamic_registration")
    op.drop_column("mcp_oauth_pending_authorizations", "logo_uri")
    op.drop_column("mcp_oauth_pending_authorizations", "client_name")
    op.drop_table("mcp_oauth_registered_clients")
