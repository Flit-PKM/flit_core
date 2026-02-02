from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ConnectedAppUpdate(BaseModel):
    device_name: Optional[str] = Field(
        None,
        min_length=1,
        description="Updated device name (only set if changing)",
        examples=["MacBook Pro", None],
    )
    is_active: Optional[bool] = Field(
        None,
        description="Whether the connected app is active (only set if changing)",
        examples=[True, False, None],
    )


class ConnectedAppRead(BaseModel):
    id: int = Field(..., description="Unique connected app identifier", examples=[1, 42])
    app_slug: str = Field(..., description="App slug from config", examples=["flit", "still"])
    app_name: Optional[str] = Field(
        None,
        description="Display name of the app (from config)",
        examples=["Flit", "Still", None],
    )
    user_id: int = Field(..., description="ID of the user who owns this connected app", examples=[1, 42])
    device_name: str = Field(..., description="Device name", examples=["MacBook Pro", "iPhone"])
    platform: Optional[str] = Field(None, description="Platform (e.g. macOS, iOS)", examples=["macOS", "iOS", None])
    app_version: Optional[str] = Field(None, description="App version", examples=["1.2.0", None])
    is_active: bool = Field(..., description="Whether the connected app is active", examples=[True, False])
    created_at: datetime = Field(..., description="Connected app creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    model_config = ConfigDict(from_attributes=True)
