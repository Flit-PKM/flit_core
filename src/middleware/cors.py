"""Path-scoped CORS: reflect Origin on MCP routes for browser-based MCP clients."""

from __future__ import annotations

from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from config import settings

_ALLOW_METHODS = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
_MAX_AGE = "600"


def is_mcp_cors_path(path: str) -> bool:
    """Paths where browser MCP clients may send arbitrary Origin headers."""
    if path == "/mcp" or path.startswith("/mcp/"):
        return True
    if path == "/.well-known/oauth-authorization-server":
        return True
    if path.startswith("/.well-known/oauth-protected-resource"):
        return True
    return False


def mcp_cors_reflect_enabled() -> bool:
    return bool(settings.MCP_ENABLED and settings.MCP_CORS_REFLECT_ORIGIN)


def build_mcp_cors_headers(request: Request, origin: str) -> dict[str, str]:
    # Bearer auth for MCP; do not pair reflect-any Origin with credentials.
    headers: dict[str, str] = {
        "Access-Control-Allow-Origin": origin,
        "Vary": "Origin",
    }
    if request.method == "OPTIONS":
        requested_headers = request.headers.get("access-control-request-headers")
        headers["Access-Control-Allow-Methods"] = _ALLOW_METHODS
        headers["Access-Control-Allow-Headers"] = requested_headers or "*"
        headers["Access-Control-Max-Age"] = _MAX_AGE
    return headers


class McpReflectOriginMiddleware(BaseHTTPMiddleware):
    """Reflect request Origin on MCP-related paths so CORS_ORIGINS need not list every MCP client."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not mcp_cors_reflect_enabled() or not is_mcp_cors_path(request.url.path):
            return await call_next(request)

        origin = request.headers.get("origin")
        if not origin:
            return await call_next(request)

        if request.method == "OPTIONS":
            return Response(status_code=200, headers=build_mcp_cors_headers(request, origin))

        response = await call_next(request)
        for key, value in build_mcp_cors_headers(request, origin).items():
            response.headers[key] = value
        return response
