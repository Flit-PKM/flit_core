"""Add is_deleted, version, and updated_at for soft-delete and sync.

Revision ID: 001_is_deleted_version
Revises: add_user_id_to_categories
Create Date: 2025-01-26

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001_is_deleted_version"
down_revision: Union[str, Sequence[str], None] = "add_user_id_to_categories"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add is_deleted to notes; add version, updated_at, is_deleted to others."""
    # notes: add is_deleted only (version/updated_at already exist)
    op.add_column(
        "notes",
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_notes_is_deleted", "notes", ["is_deleted"], unique=False)

    # categories: add version, updated_at, is_deleted
    op.add_column(
        "categories",
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.add_column(
        "categories",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "categories",
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_categories_is_deleted", "categories", ["is_deleted"], unique=False)

    # relationships: add version, created_at, updated_at, is_deleted
    op.add_column(
        "relationships",
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.add_column(
        "relationships",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "relationships",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "relationships",
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index(
        "ix_relationships_is_deleted", "relationships", ["is_deleted"], unique=False
    )

    # chunks: add version, created_at, updated_at, is_deleted
    op.add_column(
        "chunks",
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.add_column(
        "chunks",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "chunks",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "chunks",
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_chunks_is_deleted", "chunks", ["is_deleted"], unique=False)

    # note_categories: add version, created_at, updated_at, is_deleted
    op.add_column(
        "note_categories",
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.add_column(
        "note_categories",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "note_categories",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "note_categories",
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index(
        "ix_note_categories_is_deleted", "note_categories", ["is_deleted"], unique=False
    )


def downgrade() -> None:
    """Remove is_deleted, version, updated_at columns."""
    op.drop_index("ix_note_categories_is_deleted", "note_categories")
    op.drop_column("note_categories", "is_deleted")
    op.drop_column("note_categories", "updated_at")
    op.drop_column("note_categories", "created_at")
    op.drop_column("note_categories", "version")

    op.drop_index("ix_chunks_is_deleted", "chunks")
    op.drop_column("chunks", "is_deleted")
    op.drop_column("chunks", "updated_at")
    op.drop_column("chunks", "created_at")
    op.drop_column("chunks", "version")

    op.drop_index("ix_relationships_is_deleted", "relationships")
    op.drop_column("relationships", "is_deleted")
    op.drop_column("relationships", "updated_at")
    op.drop_column("relationships", "created_at")
    op.drop_column("relationships", "version")

    op.drop_index("ix_categories_is_deleted", "categories")
    op.drop_column("categories", "is_deleted")
    op.drop_column("categories", "updated_at")
    op.drop_column("categories", "version")

    op.drop_index("ix_notes_is_deleted", "notes")
    op.drop_column("notes", "is_deleted")
