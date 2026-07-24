from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from config import settings
from flit_mcp.mcp_catalog import collect_mcp_catalog, ensure_mcp_registrations
from flit_mcp.tool_meta import TOOL_META


def augment_mcp_openapi(schema: dict[str, Any], app: FastAPI) -> None:
    if not settings.MCP_OPENAPI_INCLUDE:
        return

    ensure_mcp_registrations()
    tools, resources = collect_mcp_catalog()

    components = schema.setdefault("components", {})
    security_schemes = components.setdefault("securitySchemes", {})
    security_schemes.setdefault(
        "HTTPBearer",
        {"type": "http", "scheme": "bearer", "description": "MCP OAuth access token or flit_mcp_ API key"},
    )
    comp_schemas = components.setdefault("schemas", {})

    for tool in tools:
        name = tool["name"]
        meta = TOOL_META.get(name)
        props: dict[str, Any] = {
            "name": {"type": "string", "const": name},
            "description": {"type": "string"},
            "inputSchema": tool.get("inputSchema") or {"type": "object"},
        }
        if meta:
            props["category"] = {"type": "string", "const": meta.category}
            props["tags"] = {
                "type": "array",
                "items": {"type": "string"},
                "example": list(meta.tags),
            }
            props["scopes"] = {"type": "string", "const": meta.scopes}
        comp_schemas[f"McpTool_{name}"] = {
            "type": "object",
            "properties": props,
            "required": ["name", "inputSchema"],
        }

    comp_schemas["McpResourceTemplate"] = {
        "type": "object",
        "properties": {
            "uriTemplate": {"type": "string"},
            "name": {"type": "string"},
            "description": {"type": "string"},
            "mimeType": {"type": "string", "nullable": True},
        },
        "required": ["uriTemplate", "name"],
    }

    comp_schemas["McpJsonRpcRequest"] = {
        "type": "object",
        "required": ["jsonrpc", "method"],
        "properties": {
            "jsonrpc": {"type": "string", "enum": ["2.0"]},
            "id": {"oneOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}]},
            "method": {
                "type": "string",
                "enum": [
                    "initialize",
                    "notifications/initialized",
                    "tools/list",
                    "tools/call",
                    "resources/list",
                    "resources/read",
                    "ping",
                ],
            },
            "params": {"type": "object"},
        },
    }

    comp_schemas["McpToolsCallParams"] = {
        "type": "object",
        "required": ["name"],
        "properties": {
            "name": {"type": "string", "description": "Registered MCP tool name"},
            "arguments": {"type": "object", "additionalProperties": True},
        },
    }

    comp_schemas["McpResourcesReadParams"] = {
        "type": "object",
        "required": ["uri"],
        "properties": {
            "uri": {"type": "string", "description": "Resource URI (e.g. flit://note/1)"},
        },
    }

    tags = schema.setdefault("tags", [])
    tag_names = {t.get("name") for t in tags if isinstance(t, dict)}
    for tag_name, tag_desc in (
        ("mcp", "Model Context Protocol (JSON-RPC on POST /mcp)"),
        ("mcp-oauth", "MCP OAuth 2.0 authorization server"),
        ("mcp-api-keys", "User-managed MCP API keys"),
        ("mcp-connections", "User-managed MCP OAuth sessions"),
        ("mcp-oauth-metadata", "OAuth and protected-resource metadata (RFC 9728)"),
    ):
        if tag_name not in tag_names:
            tags.append({"name": tag_name, "description": tag_desc})

    base_desc = schema.get("info", {}).get("description") or ""
    tool_lines = "\n".join(f"- **{t['name']}**: {t.get('description') or ''}" for t in tools)
    resource_lines = "\n".join(
        f"- `{r['uri_template']}` — {r.get('description') or r['name']}" for r in resources
    )
    mcp_section = (
        "\n\n## MCP (Model Context Protocol)\n\n"
        "Tools are invoked via JSON-RPC 2.0 on `POST /mcp` (requires `MCP_ENABLED=true`). "
        "Use `GET /mcp/catalog` for a machine-readable catalog "
        "(`detail=summary|full`, optional `group` / `tag` filters). "
        "Human guide: `GET /mcp/docs`. Progressive discovery: `search_tools`.\n\n"
        f"**Tools ({len(tools)}):**\n{tool_lines}\n\n"
        f"**Resources ({len(resources)}):**\n{resource_lines}\n"
    )
    if not settings.MCP_ENABLED:
        mcp_section += (
            "\n*MCP protocol endpoints are not mounted at runtime "
            "(set `MCP_ENABLED=true` and `VERIFY_EMAIL_BASE_URL` in production).*\n"
        )
    schema.setdefault("info", {})["description"] = (base_desc + mcp_section).strip()

    paths = schema.get("paths", {})
    mcp_post = paths.get("/mcp", {}).get("post")
    if mcp_post is not None:
        mcp_post["summary"] = mcp_post.get("summary") or "MCP JSON-RPC endpoint"
        mcp_post["description"] = (
            "Model Context Protocol over HTTP. Send JSON-RPC 2.0 requests with header "
            "`MCP-Protocol-Version: 2025-06-18`. Authenticate with Bearer OAuth token "
            "or MCP API key (`flit_mcp_…`). Methods: `initialize`, `tools/list`, "
            "`tools/call`, `resources/list`, `resources/read`, `ping`."
        )
        mcp_post["tags"] = ["mcp"]
        mcp_post["security"] = [{"HTTPBearer": []}]
        mcp_post["requestBody"] = {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/McpJsonRpcRequest"},
                    "examples": {
                        "tools_list": {
                            "summary": "tools/list",
                            "value": {
                                "jsonrpc": "2.0",
                                "id": 1,
                                "method": "tools/list",
                            },
                        },
                        "tools_call": {
                            "summary": "tools/call (list_notes)",
                            "value": {
                                "jsonrpc": "2.0",
                                "id": 2,
                                "method": "tools/call",
                                "params": {
                                    "name": "list_notes",
                                    "arguments": {"limit": 10},
                                },
                            },
                        },
                        "resources_read": {
                            "summary": "resources/read",
                            "value": {
                                "jsonrpc": "2.0",
                                "id": 3,
                                "method": "resources/read",
                                "params": {"uri": "flit://user/profile"},
                            },
                        },
                    },
                }
            },
        }
        mcp_post.setdefault("responses", {})["200"] = {
            "description": "JSON-RPC result or error",
            "content": {"application/json": {"schema": {"type": "object"}}},
        }

    if tools:
        schema["x-mcp-tools"] = [
            {
                "name": t["name"],
                "description": t.get("description"),
                "inputSchema": t.get("inputSchema"),
                **(
                    {
                        "category": TOOL_META[t["name"]].category,
                        "tags": list(TOOL_META[t["name"]].tags),
                        "scopes": TOOL_META[t["name"]].scopes,
                        "short_description": TOOL_META[t["name"]].short_description,
                    }
                    if t["name"] in TOOL_META
                    else {}
                ),
            }
            for t in tools
        ]
    if resources:
        schema["x-mcp-resources"] = resources
