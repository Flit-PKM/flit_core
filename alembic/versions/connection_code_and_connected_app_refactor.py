"""Connection-code flow and ConnectedApp refactor

- Add connection_codes table
- Drop oauth_authorization_codes
- Refactor connected_apps: drop client_id/secret/redirect_uris/app_id, add app_slug/device_name/platform/app_version
- Drop apps table

Revision ID: connection_code_refactor
Revises: 93ebfbc6fe4c
Create Date: 2026-01-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql


revision: str = "connection_code_refactor"
down_revision: Union[str, Sequence[str], None] = "93ebfbc6fe4c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create connection_codes table
    op.create_table(
        "connection_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("app_slug", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_connection_codes_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_connection_codes")),
    )
    op.create_index(op.f("ix_connection_codes_code"), "connection_codes", ["code"], unique=True)

    # 2. Drop oauth_authorization_codes
    op.drop_index(op.f("ix_oauth_authorization_codes_code"), table_name="oauth_authorization_codes")
    op.drop_table("oauth_authorization_codes")

    # 3. Clear tokens and connected_apps (breaking change: drop all existing)
    op.execute(text("DELETE FROM oauth_refresh_tokens"))
    op.execute(text("DELETE FROM oauth_access_tokens"))
    op.execute(text("UPDATE notes SET source_id = NULL WHERE source_id IS NOT NULL"))
    op.execute(text("DELETE FROM connected_apps"))

    # 4. Drop FK connected_apps -> apps, then drop columns
    op.drop_constraint(
        "fk_connected_apps_app_id_apps",
        "connected_apps",
        type_="foreignkey",
    )
    op.drop_index("ix_connected_apps_client_id", table_name="connected_apps")
    op.drop_column("connected_apps", "client_id")
    op.drop_column("connected_apps", "client_secret")
    op.drop_column("connected_apps", "redirect_uris")
    op.drop_column("connected_apps", "app_id")

    # 5. Add new columns to connected_apps (table is empty)
    op.add_column("connected_apps", sa.Column("app_slug", sa.String(length=64), nullable=False))
    op.add_column("connected_apps", sa.Column("device_name", sa.String(length=255), nullable=False))
    op.add_column("connected_apps", sa.Column("platform", sa.String(length=64), nullable=True))
    op.add_column("connected_apps", sa.Column("app_version", sa.String(length=32), nullable=True))

    # 6. Drop apps table
    op.drop_table("apps")


def downgrade() -> None:
    op.create_table(
        "apps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_apps")),
    )

    op.drop_column("connected_apps", "app_version")
    op.drop_column("connected_apps", "platform")
    op.drop_column("connected_apps", "device_name")
    op.drop_column("connected_apps", "app_slug")
    op.add_column("connected_apps", sa.Column("app_id", sa.Integer(), nullable=True))
    op.add_column(
        "connected_apps",
        sa.Column("redirect_uris", postgresql.JSON(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("connected_apps", sa.Column("client_secret", sa.String(255), nullable=True))
    op.add_column("connected_apps", sa.Column("client_id", sa.String(255), nullable=True))
    op.create_index("ix_connected_apps_client_id", "connected_apps", ["client_id"], unique=True)
    op.create_foreign_key(
        "fk_connected_apps_app_id_apps",
        "connected_apps",
        "apps",
        ["app_id"],
        ["id"],
    )

    op.create_table(
        "oauth_authorization_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(255), nullable=False),
        sa.Column("connected_app_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("code_challenge", sa.String(255), nullable=False),
        sa.Column("code_challenge_method", sa.String(10), nullable=False),
        sa.Column("redirect_uri", sa.String(512), nullable=False),
        sa.Column("scopes", sa.String(255), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["connected_app_id"],
            ["connected_apps.id"],
            name="fk_oauth_authorization_codes_connected_app_id_connected_apps",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_oauth_authorization_codes_user_id_users",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_oauth_authorization_codes"),
    )
    op.create_index("ix_oauth_authorization_codes_code", "oauth_authorization_codes", ["code"], unique=True)

    op.drop_index(op.f("ix_connection_codes_code"), table_name="connection_codes")
    op.drop_table("connection_codes")
