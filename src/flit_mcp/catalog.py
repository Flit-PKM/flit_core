from __future__ import annotations

from fastapi import APIRouter

from flit_mcp.mcp_catalog import collect_mcp_catalog
from schemas.mcp_catalog import McpCatalogResponse, McpResourceSummary, McpToolSummary

router = APIRouter(prefix="/mcp", tags=["mcp"])


@router.get(
    "/catalog",
    response_model=McpCatalogResponse,
    summary="MCP tool and resource catalog",
    description=(
        "Read-only discovery of MCP tools and resource URI templates. "
        "Invoke tools via JSON-RPC on POST /mcp when MCP_ENABLED is true."
    ),
)
async def mcp_catalog() -> McpCatalogResponse:
    tools_raw, resources_raw = collect_mcp_catalog()
    tools = [
        McpToolSummary(
            name=t["name"],
            description=str(t.get("description") or ""),
            input_schema=dict(t.get("inputSchema") or {}),
        )
        for t in tools_raw
    ]
    resources = [
        McpResourceSummary(
            uri_template=r["uri_template"],
            name=r["name"],
            description=r.get("description") or "",
            mime_type=r.get("mime_type"),
        )
        for r in resources_raw
    ]
    return McpCatalogResponse(tools=tools, resources=resources)
