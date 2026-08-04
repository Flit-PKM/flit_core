from __future__ import annotations

import logging

from config import settings
from database.engine import AsyncSessionFactory
from exceptions import AuthorizationError, BusinessLogicError, ValidationError
from fastapi_mcp_router import MCPRouter
from fastapi_mcp_router.exceptions import MCPError
from flit_mcp.auth.context import McpAuthContext
from flit_mcp.auth.contextvar import mcp_auth_ctx_var
from flit_mcp.auth.resolve import resolve_mcp_auth
from flit_mcp.oauth.metadata import oauth_protected_resource_metadata
from flit_mcp.rate_limit import check_mcp_rate_limit
from flit_mcp.server_info import MCP_SERVER_NAME, MCP_SERVER_VERSION
from flit_mcp.tool_access import mcp_tool_filter
from service.entitlement import (
    ENTITLEMENT_REQUIRED_DETAIL,
    MCP_ENTITLEMENT_JSONRPC_CODE,
    require_active_entitlement,
)
from service.mcp_oauth import mcp_issuer

logger = logging.getLogger(__name__)


async def _mcp_auth_validator(
    api_key: str | None,
    bearer_token: str | None,
) -> McpAuthContext | bool:
    token = bearer_token or api_key
    if not token:
        logger.info("MCP auth rejected: no Authorization Bearer or X-API-Key")
        return False
    async with AsyncSessionFactory() as session:
        try:
            ctx = await resolve_mcp_auth(session, token)
            if not ctx:
                logger.info(
                    "MCP auth rejected: invalid or expired credentials "
                    "(bearer=%s api_key=%s)",
                    bool(bearer_token),
                    bool(api_key),
                )
                return False
            try:
                await require_active_entitlement(session, ctx.user_id)
            except AuthorizationError:
                await session.rollback()
                # MCPError → JSON-RPC -32003 (auth runs before body parse, so id may be null)
                raise MCPError(
                    code=MCP_ENTITLEMENT_JSONRPC_CODE,
                    message=ENTITLEMENT_REQUIRED_DETAIL,
                )
            check_mcp_rate_limit(ctx.user_id)
            await session.commit()
            mcp_auth_ctx_var.set(ctx)
            return ctx
        except MCPError:
            raise
        except BusinessLogicError:
            await session.rollback()
            raise
        except Exception:
            await session.rollback()
            raise


def _issuer_base_url() -> str | None:
    if not settings.MCP_ENABLED:
        return None
    try:
        return mcp_issuer()
    except ValidationError:
        return None


flit_mcp_router = MCPRouter(
    auth_validator=_mcp_auth_validator,
    tool_filter=mcp_tool_filter,
    base_url=_issuer_base_url(),
    oauth_resource_metadata=oauth_protected_resource_metadata()
    if settings.MCP_ENABLED and _issuer_base_url()
    else None,
    # Register GET /mcp so OAuth clients get 401 + WWW-Authenticate instead of SPA index.html.
    legacy_sse=True,
    server_info={
        "name": MCP_SERVER_NAME,
        "version": MCP_SERVER_VERSION,
    },
)
