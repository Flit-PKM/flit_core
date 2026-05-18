from __future__ import annotations

from typing import Any


def ensure_mcp_registrations() -> None:
    import flit_mcp.resources  # noqa: F401 — register resources
    import flit_mcp.tools  # noqa: F401 — register tools


def collect_mcp_catalog() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return MCP tools and resource templates from the in-process registry."""
    from flit_mcp.router_setup import flit_mcp_router

    ensure_mcp_registrations()
    tools = flit_mcp_router._tool_registry.list_tools()
    resources: list[dict[str, Any]] = []
    registry = flit_mcp_router._resource_registry
    if registry.has_resources():
        for template in registry.list_templates():
            resources.append(
                {
                    "uri_template": template.uri_template,
                    "name": template.name,
                    "description": template.description or "",
                    "mime_type": template.mime_type,
                }
            )
    return tools, resources
