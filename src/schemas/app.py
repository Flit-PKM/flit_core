from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AppRead(BaseModel):
    """App from fixed config list (slug, name)."""

    slug: str = Field(..., description="Stable app identifier", examples=["flit", "still"])
    name: str = Field(..., description="Display name", examples=["Flit", "Still"])

    model_config = ConfigDict(from_attributes=True)
