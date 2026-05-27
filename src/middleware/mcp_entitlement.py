"""Block authenticated POST /mcp when billing is on and user lacks entitlement."""

from __future__ import annotations

import json
from collections.abc import Callable

from config import settings
from database.engine import AsyncSessionFactory
from fastapi_mcp_router.protocol import json_rpc_error
from flit_mcp.auth.resolve import resolve_mcp_auth
import service.billing as billing
from service.entitlement import (
    ENTITLEMENT_REQUIRED_DETAIL,
    MCP_ENTITLEMENT_JSONRPC_CODE,
    user_has_active_entitlement,
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp


def _is_mcp_post(path: str, method: str) -> bool:
    normalized = path.rstrip("/") or "/"
    return method == "POST" and normalized.endswith("/mcp")


def _extract_bearer_token(request: Request) -> str | None:
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip() or None
    return None


def _parse_jsonrpc_id(body: bytes) -> object:
    if not body or not body.strip():
        return None
    try:
        payload = json.loads(body)
    except ValueError:
        return None
    if isinstance(payload, dict):
        return payload.get("id")
    return None


class McpEntitlementMiddleware(BaseHTTPMiddleware):
    """Return JSON-RPC entitlement errors before MCP auth when credentials are valid but not entitled."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not (
            settings.MCP_ENABLED
            and billing.is_billing_configured()
            and _is_mcp_post(request.url.path, request.method)
        ):
            return await call_next(request)

        body = await request.body()
        request_id = _parse_jsonrpc_id(body)

        api_key = request.headers.get("x-api-key")
        bearer = _extract_bearer_token(request)
        token = bearer or api_key

        if token:
            async with AsyncSessionFactory() as session:
                try:
                    ctx = await resolve_mcp_auth(session, token)
                    if ctx is not None and not await user_has_active_entitlement(
                        session, ctx.user_id
                    ):
                        return json_rpc_error(
                            request_id=request_id,
                            code=MCP_ENTITLEMENT_JSONRPC_CODE,
                            message=ENTITLEMENT_REQUIRED_DETAIL,
                        )
                finally:
                    await session.rollback()

        async def receive() -> dict:
            return {"type": "http.request", "body": body, "more_body": False}

        replay_request = Request(request.scope, receive)
        return await call_next(replay_request)
