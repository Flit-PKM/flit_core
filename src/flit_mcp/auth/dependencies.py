from __future__ import annotations

from fastapi import HTTPException, status

from exceptions import AuthorizationError
from flit_mcp.auth.context import McpAuthContext


def require_mcp_write(ctx: McpAuthContext) -> None:
    if not ctx.allows_write():
        raise AuthorizationError(
            "This action requires read write scope. Re-authorize with read write scope."
        )
