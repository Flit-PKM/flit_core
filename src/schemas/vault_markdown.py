from __future__ import annotations

from pydantic import BaseModel, Field


class VaultMarkdownImportResult(BaseModel):
    notes_imported: int = Field(..., description="Number of notes inserted")
    relationships_imported: int = Field(
        ..., description="Number of new relationship edges created"
    )
    relationships_skipped: int = Field(
        ...,
        description="Relationships skipped (unknown label, missing target, duplicate, etc.)",
    )
