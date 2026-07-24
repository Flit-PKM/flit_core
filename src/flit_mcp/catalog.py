from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse

from config import settings
from flit_mcp.mcp_catalog import collect_mcp_catalog
from flit_mcp.server_info import (
    MCP_MAX_BATCH_NOTE_IDS,
    MCP_RETURN_MODES,
    MCP_SERVER_DESCRIPTION,
    MCP_SERVER_NAME,
    MCP_SERVER_VERSION,
)
from flit_mcp.tool_meta import TOOL_META, build_tool_groups, tool_scope_for
from schemas.mcp_catalog import (
    CatalogDetail,
    McpCatalogResponse,
    McpResourceSummary,
    McpServerCapabilities,
    McpServerInfo,
    McpToolExample,
    McpToolSummary,
)

router = APIRouter(prefix="/mcp", tags=["mcp"])


def _catalog_base_url() -> str | None:
    base = (settings.PUBLIC_BASE_URL or "").strip().rstrip("/")
    if not base:
        return None
    return f"{base}/mcp"


def build_mcp_catalog_response(
    *,
    detail: CatalogDetail = "full",
    group: str | None = None,
    tag: str | None = None,
) -> McpCatalogResponse:
    tools_raw, resources_raw = collect_mcp_catalog()
    include_schema = detail == "full"

    tools: list[McpToolSummary] = []
    for t in tools_raw:
        name = t["name"]
        meta = TOOL_META.get(name)
        category = meta.category if meta else None
        tags = list(meta.tags) if meta else []
        if group and category != group:
            continue
        if tag and tag not in tags:
            continue

        examples = [
            McpToolExample(
                title=ex.title,
                input=ex.input,
                output_summary=ex.output_summary,
            )
            for ex in (meta.examples if meta else ())
        ]
        tools.append(
            McpToolSummary(
                name=name,
                description=str(t.get("description") or ""),
                category=category,
                tags=tags,
                scopes=tool_scope_for(name),
                short_description=meta.short_description if meta else None,
                examples=examples,
                input_schema=dict(t.get("inputSchema") or {}) if include_schema else None,
            )
        )

    tool_names = [t.name for t in tools]
    groups = build_tool_groups(tool_names)

    resources = [
        McpResourceSummary(
            uri_template=r["uri_template"],
            name=r["name"],
            description=r.get("description") or "",
            mime_type=r.get("mime_type") or "application/json",
        )
        for r in resources_raw
    ]

    server = McpServerInfo(
        name=MCP_SERVER_NAME,
        version=MCP_SERVER_VERSION,
        description=MCP_SERVER_DESCRIPTION,
        base_url=_catalog_base_url(),
        auth="API key (flit_mcp_…) or OAuth2 with read and read write scopes",
        capabilities=McpServerCapabilities(
            progressive_discovery=True,
            search_tools=True,
            max_batch_size=MCP_MAX_BATCH_NOTE_IDS,
            return_modes=list(MCP_RETURN_MODES),
            rate_limit=settings.MCP_RATE_LIMIT,
            rate_limit_enabled_default=True,
        ),
    )
    return McpCatalogResponse(
        server=server,
        groups=groups,
        tools=tools,
        resources=resources,
    )


@router.get(
    "/catalog",
    response_model=McpCatalogResponse,
    summary="MCP tool and resource catalog",
    description=(
        "Read-only discovery of MCP tools and resource URI templates. "
        "Use detail=summary to omit input schemas. Filter with group= or tag=. "
        "Invoke tools via JSON-RPC on POST /mcp when MCP_ENABLED is true. "
        "Human-readable guide: GET /mcp/docs."
    ),
)
async def mcp_catalog(
    detail: CatalogDetail = Query(
        "full",
        description="full includes input_schema; summary omits schemas for lighter discovery.",
    ),
    group: str | None = Query(
        None,
        description=(
            "Filter tools by category: discovery, notes, categories, "
            "relationships, note_categories, user."
        ),
    ),
    tag: str | None = Query(
        None,
        description="Filter tools that include this tag (e.g. write, graph, batch).",
    ),
) -> McpCatalogResponse:
    return build_mcp_catalog_response(detail=detail, group=group, tag=tag)


@router.get(
    "/docs",
    response_class=PlainTextResponse,
    summary="MCP integration guide (markdown)",
    description="Human-readable MCP integration guide as markdown.",
)
async def mcp_docs() -> PlainTextResponse:
    from pathlib import Path

    docs_path = Path(__file__).resolve().parents[2] / "docs" / "mcp-integration.md"
    if not docs_path.is_file():
        return PlainTextResponse(
            "MCP integration guide not found. See repository docs/mcp-integration.md.",
            status_code=404,
            media_type="text/plain",
        )
    return PlainTextResponse(
        docs_path.read_text(encoding="utf-8"),
        media_type="text/markdown; charset=utf-8",
    )
