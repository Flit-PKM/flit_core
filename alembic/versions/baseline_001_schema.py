"""Baseline schema from current models (Postgres only, no chunks).

Revision ID: baseline_001
Revises:
Create Date: 2026-08-04

For existing databases already at the old head: stamp this revision, then
upgrade head to apply drop_chunks_if_exists.
For empty databases: alembic upgrade head.
Do not run this upgrade() on a DB that already has tables.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

from models.base import Base

# Import all models so Base.metadata is complete
import models  # noqa: F401

revision: str = "baseline_001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
