"""Newsletter campaigns, feedback responses, revoked JWTs, access_codes.revoked_at.

Revision ID: add_admin_extension_tables
Revises: add_user_last_login
Create Date: 2026-05-11

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "add_admin_extension_tables"
down_revision: Union[str, Sequence[str], None] = "add_user_last_login"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "newsletter_campaigns",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("subject", sa.String(length=500), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("body_html", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_newsletter_campaigns_id"), "newsletter_campaigns", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_newsletter_campaigns_status"),
        "newsletter_campaigns",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_newsletter_campaigns_scheduled_at"),
        "newsletter_campaigns",
        ["scheduled_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_newsletter_campaigns_created_by"),
        "newsletter_campaigns",
        ["created_by"],
        unique=False,
    )

    op.create_table(
        "feedback_responses",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("feedback_id", sa.Integer(), nullable=False),
        sa.Column("author_user_id", sa.Integer(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["feedback_id"], ["feedbacks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_feedback_responses_id"), "feedback_responses", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_feedback_responses_feedback_id"),
        "feedback_responses",
        ["feedback_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_feedback_responses_author_user_id"),
        "feedback_responses",
        ["author_user_id"],
        unique=False,
    )

    op.create_table(
        "revoked_jwts",
        sa.Column("jti", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("jti"),
    )
    op.create_index(
        op.f("ix_revoked_jwts_expires_at"), "revoked_jwts", ["expires_at"], unique=False
    )

    op.add_column(
        "access_codes",
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f("ix_access_codes_revoked_at"), "access_codes", ["revoked_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_access_codes_revoked_at"), table_name="access_codes")
    op.drop_column("access_codes", "revoked_at")
    op.drop_index(op.f("ix_revoked_jwts_expires_at"), table_name="revoked_jwts")
    op.drop_table("revoked_jwts")
    op.drop_index(op.f("ix_feedback_responses_author_user_id"), table_name="feedback_responses")
    op.drop_index(op.f("ix_feedback_responses_feedback_id"), table_name="feedback_responses")
    op.drop_index(op.f("ix_feedback_responses_id"), table_name="feedback_responses")
    op.drop_table("feedback_responses")
    op.drop_index(op.f("ix_newsletter_campaigns_created_by"), table_name="newsletter_campaigns")
    op.drop_index(op.f("ix_newsletter_campaigns_scheduled_at"), table_name="newsletter_campaigns")
    op.drop_index(op.f("ix_newsletter_campaigns_status"), table_name="newsletter_campaigns")
    op.drop_index(op.f("ix_newsletter_campaigns_id"), table_name="newsletter_campaigns")
    op.drop_table("newsletter_campaigns")
