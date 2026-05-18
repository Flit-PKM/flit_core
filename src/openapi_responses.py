"""Shared OpenAPI error response definitions for route decorators."""

from __future__ import annotations

from typing import Any

HTTP_ERROR_CONTENT: dict[str, Any] = {
    "application/json": {
        "schema": {
            "type": "object",
            "properties": {"detail": {}},
        }
    }
}

_RESP_401: dict[str, Any] = {
    "description": "Not authenticated",
    "content": HTTP_ERROR_CONTENT,
}
_RESP_403: dict[str, Any] = {
    "description": "Forbidden",
    "content": HTTP_ERROR_CONTENT,
}
_RESP_404: dict[str, Any] = {
    "description": "Not found",
    "content": HTTP_ERROR_CONTENT,
}
_RESP_409: dict[str, Any] = {
    "description": "Conflict",
    "content": HTTP_ERROR_CONTENT,
}

AUTHENTICATED: dict[int, dict[str, Any]] = {401: _RESP_401}
SUPERUSER: dict[int, dict[str, Any]] = {
    401: _RESP_401,
    403: {"description": "Superuser access required", "content": HTTP_ERROR_CONTENT},
}
OWNED_RESOURCE: dict[int, dict[str, Any]] = {
    401: _RESP_401,
    403: _RESP_403,
    404: _RESP_404,
}


def owned_resource(
    *,
    forbidden: str | None = None,
    not_found: str | None = None,
) -> dict[int, dict[str, Any]]:
    """401/403/404 bundle with optional custom descriptions."""
    out = dict(OWNED_RESOURCE)
    if forbidden:
        out[403] = {"description": forbidden, "content": HTTP_ERROR_CONTENT}
    if not_found:
        out[404] = {"description": not_found, "content": HTTP_ERROR_CONTENT}
    return out
