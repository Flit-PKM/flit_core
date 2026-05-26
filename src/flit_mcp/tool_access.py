"""MCP tool visibility by OAuth/API key scope."""

from __future__ import annotations

from flit_mcp.auth.contextvar import mcp_auth_ctx_var

# Tools that mutate PKM data; hidden from tools/list when token has read-only scope.
MCP_WRITE_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "create_note",
        "update_note",
        "delete_note",
        "create_category",
        "update_category",
        "delete_category",
        "create_relationship",
        "delete_relationship",
        "link_note_to_category",
        "unlink_note_from_category",
    }
)


def mcp_tool_filter(_is_oauth_connection: bool) -> list[str] | None:
    """Exclude write tools from tools/list when the token is read-only.

    Uses auth context set by the MCP auth validator on the same request.
    tools/call still enforces require_mcp_write for defense in depth.
    """
    ctx = mcp_auth_ctx_var.get()
    if ctx is None or ctx.allows_write():
        return None
    return sorted(MCP_WRITE_TOOL_NAMES)
