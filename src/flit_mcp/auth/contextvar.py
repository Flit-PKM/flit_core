from __future__ import annotations

import contextvars

from flit_mcp.auth.context import McpAuthContext

mcp_auth_ctx_var: contextvars.ContextVar[McpAuthContext | None] = contextvars.ContextVar(
    "mcp_auth_ctx",
    default=None,
)


def get_current_mcp_auth() -> McpAuthContext:
    ctx = mcp_auth_ctx_var.get()
    if ctx is None:
        from exceptions import AuthenticationError

        raise AuthenticationError("Authentication required")
    return ctx
