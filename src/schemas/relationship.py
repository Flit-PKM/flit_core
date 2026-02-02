from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from models.relationship import RelationshipType


class RelationshipBase(BaseModel):
    note_a_id: int = Field(
        ...,
        description="ID of the first note in the relationship",
        examples=[1, 42]
    )
    note_b_id: int = Field(
        ...,
        description="ID of the second note in the relationship",
        examples=[2, 43]
    )
    type: RelationshipType = Field(
        ...,
        description="Type of relationship: FOLLOWS_ON, SIMILAR_TO, CONTRADICTS, REFERENCES, or RELATED_TO",
        examples=[
            RelationshipType.FOLLOWS_ON,
            RelationshipType.SIMILAR_TO,
            RelationshipType.CONTRADICTS,
            RelationshipType.REFERENCES,
            RelationshipType.RELATED_TO
        ]
    )


class RelationshipCreate(RelationshipBase):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "note_a_id": 1,
                "note_b_id": 2,
                "type": "RELATED_TO"
            }
        }
    )


class RelationshipRead(RelationshipBase):
    version: int = Field(..., description="Relationship version number", examples=[1, 2])
    created_at: datetime = Field(..., description="Creation timestamp", examples=["2024-01-15T10:30:00Z"])
    updated_at: datetime = Field(..., description="Last update timestamp", examples=["2024-01-20T14:22:00Z"])
    is_deleted: bool = Field(
        False,
        description="True if the relationship has been soft-deleted",
    )

    model_config = ConfigDict(from_attributes=True)
