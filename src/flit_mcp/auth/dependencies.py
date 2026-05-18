from __future__ import annotations

from fastapi import HTTPException, Request, status

from exceptions import AuthorizationError
from flit_mcp.auth.context import McpAuthContext


def _context_from_request(request: Request) -> McpAuthContext:
    raw = getattr(request.state, "auth_context", None)
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if isinstance(raw, McpAuthContext):
        return raw
    if hasattr(raw, "user_id") and hasattr(raw, "scopes_raw"):
        return raw  # McpAuthContext from auth_validator
    if isinstance(raw, dict):
        return McpAuthContext(
            user_id=int(raw["user_id"]),
            scopes_raw=str(raw["scopes"]),
            auth_method=raw["auth_method"],
        )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
    )


def get_mcp_auth_context(request: Request) -> McpAuthContext:
    return _context_from_request(request)


def require_mcp_write(ctx: McpAuthContext) -> None:
    if not ctx.allows_write():
        raise AuthorizationError(
            "This action requires read write scope. Re-authorize with read write scope."
        )
