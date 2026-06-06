"""MCP refresh token client metadata; revoke legacy mcp connected apps

Revision ID: mcp_connections
Revises: add_note_state_hash
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision: str = "mcp_connections"
down_revision: Union[str, Sequence[str], None] = "add_note_state_hash"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "mcp_refresh_tokens",
        sa.Column("client_id", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "mcp_refresh_tokens",
        sa.Column("client_name", sa.String(length=255), nullable=True),
    )

    # Deactivate legacy mcp connected apps and revoke their sync OAuth tokens.
    op.execute(text("UPDATE connected_apps SET is_active = false WHERE app_slug = 'mcp'"))
    op.execute(
        text(
            """
            UPDATE oauth_refresh_tokens
            SET revoked_at = CURRENT_TIMESTAMP
            WHERE revoked_at IS NULL
              AND connected_app_id IN (
                  SELECT id FROM connected_apps WHERE app_slug = 'mcp'
              )
            """
        )
    )
    op.execute(
        text(
            """
            UPDATE oauth_access_tokens
            SET revoked = true
            WHERE revoked = false
              AND connected_app_id IN (
                  SELECT id FROM connected_apps WHERE app_slug = 'mcp'
              )
            """
        )
    )


def downgrade() -> None:
    op.drop_column("mcp_refresh_tokens", "client_name")
    op.drop_column("mcp_refresh_tokens", "client_id")
