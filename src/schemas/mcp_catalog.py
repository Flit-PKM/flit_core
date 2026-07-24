from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class McpToolExample(BaseModel):
    title: str
    input: dict[str, Any]
    output_summary: str


class McpServerCapabilities(BaseModel):
    progressive_discovery: bool = True
    search_tools: bool = True
    max_batch_size: int
    return_modes: list[str]
    rate_limit: str
    rate_limit_enabled_default: bool = True
    catalog_detail_modes: list[str] = Field(
        default_factory=lambda: ["full", "summary"]
    )


class McpServerInfo(BaseModel):
    name: str
    version: str
    description: str
    base_url: str | None = None
    auth: str
    capabilities: McpServerCapabilities


class McpToolSummary(BaseModel):
    name: str
    description: str = ""
    category: str | None = None
    tags: list[str] = Field(default_factory=list)
    scopes: str | None = None
    short_description: str | None = None
    examples: list[McpToolExample] = Field(default_factory=list)
    input_schema: dict[str, Any] | None = None


class McpResourceSummary(BaseModel):
    uri_template: str
    name: str
    description: str = ""
    mime_type: str | None = None


class McpCatalogResponse(BaseModel):
    server: McpServerInfo
    groups: dict[str, list[str]]
    tools: list[McpToolSummary]
    resources: list[McpResourceSummary]


CatalogDetail = Literal["full", "summary"]
