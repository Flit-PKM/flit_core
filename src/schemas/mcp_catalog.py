from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class McpToolSummary(BaseModel):
    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)


class McpResourceSummary(BaseModel):
    uri_template: str
    name: str
    description: str = ""
    mime_type: str | None = None


class McpCatalogResponse(BaseModel):
    tools: list[McpToolSummary]
    resources: list[McpResourceSummary]
