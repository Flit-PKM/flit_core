from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ChunkBase(BaseModel):
    position_start: int = Field(
        ...,
        ge=0,
        description="Starting character position in the note content (0-indexed)",
        examples=[0, 100, 500]
    )
    position_end: int = Field(
        ...,
        ge=0,
        description="Ending character position in the note content (must be >= position_start)",
        examples=[100, 500, 1000]
    )
    summary: str = Field(
        ...,
        min_length=1,
        description="Summary or description of this chunk",
        examples=["Key discussion points about project timeline", "Main conclusions from the meeting"]
    )
    embedding: Optional[list[float]] = Field(
        None,
        description="Vector embedding for semantic search (optional)",
        examples=[None, [0.1, 0.2, 0.3, -0.1, 0.5]]
    )

    @model_validator(mode="after")
    def position_end_not_before_start(self) -> "ChunkBase":
        if self.position_end < self.position_start:
            raise ValueError("position_end must be >= position_start")
        return self


class ChunkCreate(ChunkBase):
    note_id: int = Field(..., description="ID of the note this chunk belongs to", examples=[1, 42])


class ChunkUpdate(BaseModel):
    position_start: Optional[int] = Field(
        None,
        ge=0,
        description="Updated starting position (only set if changing)",
        examples=[0, 100, None]
    )
    position_end: Optional[int] = Field(
        None,
        ge=0,
        description="Updated ending position (only set if changing, must be >= position_start)",
        examples=[100, 500, None]
    )
    summary: Optional[str] = Field(
        None,
        min_length=1,
        description="Updated summary (only set if changing)",
        examples=["Updated summary text", None]
    )
    embedding: Optional[list[float]] = Field(
        None,
        description="Updated vector embedding (only set if changing)",
        examples=[None, [0.1, 0.2, 0.3, -0.1, 0.5]]
    )

    @model_validator(mode="after")
    def position_end_not_before_start(self) -> "ChunkUpdate":
        if self.position_start is not None and self.position_end is not None:
            if self.position_end < self.position_start:
                raise ValueError("position_end must be >= position_start")
        return self


class ChunkRead(ChunkBase):
    id: int = Field(..., description="Unique chunk identifier", examples=[1, 42])
    note_id: int = Field(..., description="ID of the note this chunk belongs to", examples=[1, 42])
    version: int = Field(..., description="Chunk version number", examples=[1, 2])
    created_at: datetime = Field(..., description="Creation timestamp", examples=["2024-01-15T10:30:00Z"])
    updated_at: datetime = Field(..., description="Last update timestamp", examples=["2024-01-20T14:22:00Z"])
    is_deleted: bool = Field(
        False,
        description="True if the chunk has been soft-deleted",
    )

    model_config = ConfigDict(from_attributes=True)
