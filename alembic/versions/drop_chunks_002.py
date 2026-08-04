"""Drop leftover chunks table from pre-squash databases.

Revision ID: drop_chunks_002
Revises: baseline_001
Create Date: 2026-08-04

No-op on greenfield installs (table never created). On stamped existing DBs,
removes the obsolete chunks table after the clean-break squash.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "drop_chunks_002"
down_revision: Union[str, Sequence[str], None] = "baseline_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS chunks CASCADE")
    # pgvector was only used by chunks; safe to drop if present and unused
    op.execute("DROP EXTENSION IF EXISTS vector")


def downgrade() -> None:
    # Chunks are intentionally not restored; re-add via a new feature migration if needed.
    pass
