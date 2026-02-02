from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from models.note import NoteType
from schemas.category import CategoryRead
from schemas.relationship import RelationshipRead


class NoteBase(BaseModel):
    title: str = Field(
        ...,
        min_length=1,
        description="Note title",
        examples=["Meeting Notes", "Project Ideas", "Daily Reflection"]
    )
    content: str = Field(
        ...,
        min_length=1,
        description="Note content/body text",
        examples=["This is the main content of the note...", "Key points:\n1. First point\n2. Second point"]
    )
    type: NoteType = Field(
        default=NoteType.BASE,
        description="Type of note: BASE (default), INSIGHT, or SUMMARY",
        examples=[NoteType.BASE, NoteType.INSIGHT, NoteType.SUMMARY]
    )
    source_id: Optional[int] = Field(
        None,
        description="ID of the connected app that created this note (if synced from external app)",
        examples=[1, None]
    )


class NoteCreateRequest(NoteBase):
    """Request schema for creating notes (user_id comes from authenticated user)."""
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "title": "Meeting Notes",
                "content": "Discussed project timeline and deliverables. Next steps: review requirements.",
                "type": "BASE",
                "source_id": None,
            }
        }
    )


class NoteCreate(NoteBase):
    user_id: int = Field(..., description="ID of the user who owns this note", examples=[1, 42])


class NoteUpdate(BaseModel):
    title: Optional[str] = Field(
        None,
        min_length=1,
        description="Updated note title (only set if changing title)",
        examples=["Updated Meeting Notes", None]
    )
    content: Optional[str] = Field(
        None,
        min_length=1,
        description="Updated note content (only set if changing content)",
        examples=["Updated content...", None]
    )
    type: Optional[NoteType] = Field(
        None,
        description="Updated note type (only set if changing type)",
        examples=[NoteType.INSIGHT, None]
    )
    source_id: Optional[int] = Field(
        None,
        description="Updated source ID (only set if changing source)",
        examples=[1, None]
    )


class NoteRead(NoteBase):
    id: int = Field(..., description="Unique note identifier", examples=[1, 42, 100])
    user_id: int = Field(..., description="ID of the user who owns this note", examples=[1, 42])
    version: int = Field(..., description="Note version number (increments on each update)", examples=[1, 2, 5])
    is_deleted: bool = Field(
        False,
        description="True if the note has been soft-deleted (synced to clients for removal)",
    )
    created_at: datetime = Field(..., description="Note creation timestamp", examples=["2024-01-15T10:30:00Z"])
    updated_at: datetime = Field(..., description="Last note update timestamp", examples=["2024-01-20T14:22:00Z"])

    model_config = ConfigDict(from_attributes=True)


class NoteDetailRead(NoteRead):
    """Note with embedded categories and relationships (for GET /notes/{id})."""

    categories: List[CategoryRead] = Field(
        default_factory=list,
        description="Categories linked to this note",
    )
    relationships: List[RelationshipRead] = Field(
        default_factory=list,
        description="Relationships where this note is either note_a or note_b",
    )
