from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class NoteCategoryBase(BaseModel):
    note_id: int = Field(..., description="ID of the note", examples=[1, 42])
    category_id: int = Field(..., description="ID of the category", examples=[1, 5])


class NoteCategoryCreate(NoteCategoryBase):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "note_id": 1,
                "category_id": 5
            }
        }
    )


class NoteCategoryRead(NoteCategoryBase):
    version: int = Field(..., description="NoteCategory version number", examples=[1, 2])
    created_at: datetime = Field(..., description="Creation timestamp", examples=["2024-01-15T10:30:00Z"])
    updated_at: datetime = Field(..., description="Last update timestamp", examples=["2024-01-20T14:22:00Z"])
    is_deleted: bool = Field(
        False,
        description="True if the note-category link has been soft-deleted",
    )

    model_config = ConfigDict(from_attributes=True)
