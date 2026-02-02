from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class CategoryBase(BaseModel):
    name: str = Field(
        ...,
        min_length=1,
        description="Category name",
        examples=["Work", "Personal", "Projects", "Ideas"]
    )


class CategoryCreate(CategoryBase):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Work"
            }
        }
    )


class CategoryUpdate(BaseModel):
    name: Optional[str] = Field(
        None,
        min_length=1,
        description="Updated category name (only set if changing)",
        examples=["Updated Category Name", None]
    )


class CategoryRead(CategoryBase):
    id: int = Field(..., description="Unique category identifier", examples=[1, 42])
    user_id: int = Field(..., description="User ID who owns this category", examples=[1, 42])
    version: int = Field(..., description="Category version number", examples=[1, 2])
    created_at: datetime = Field(..., description="Category creation timestamp", examples=["2024-01-15T10:30:00Z"])
    updated_at: datetime = Field(..., description="Last update timestamp", examples=["2024-01-20T14:22:00Z"])
    is_deleted: bool = Field(
        False,
        description="True if the category has been soft-deleted",
    )

    model_config = ConfigDict(from_attributes=True)
