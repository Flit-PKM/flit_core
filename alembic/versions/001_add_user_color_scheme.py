"""Add user color_scheme (light/dark/default).

Revision ID: 001_color_scheme
Revises: 001_is_deleted_version
Create Date: Add color_scheme column to users

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "001_color_scheme"
down_revision: Union[str, Sequence[str], None] = "001_is_deleted_version"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add color_scheme column to users with default 'default'."""
    op.add_column(
        "users",
        sa.Column(
            "color_scheme",
            sa.String(20),
            nullable=False,
            server_default="default",
        ),
    )


def downgrade() -> None:
    """Remove color_scheme column from users."""
    op.drop_column("users", "color_scheme")
