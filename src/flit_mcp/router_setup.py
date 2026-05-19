from __future__ import annotations

from config import settings
from database.engine import AsyncSessionFactory
from exceptions import BusinessLogicError, ValidationError
from fastapi_mcp_router import MCPRouter
from flit_mcp.auth.context import McpAuthContext
from flit_mcp.auth.contextvar import mcp_auth_ctx_var
from flit_mcp.auth.resolve import resolve_mcp_auth
from flit_mcp.oauth.metadata import oauth_protected_resource_metadata
from flit_mcp.rate_limit import check_mcp_rate_limit
from service.mcp_oauth import mcp_issuer


async def _mcp_auth_validator(
    api_key: str | None,
    bearer_token: str | None,
) -> McpAuthContext | bool:
    token = bearer_token or api_key
    if not token:
        return False
    async with AsyncSessionFactory() as session:
        try:
            ctx = await resolve_mcp_auth(session, token)
            if not ctx:
                return False
            check_mcp_rate_limit(ctx.user_id)
            await session.commit()
            mcp_auth_ctx_var.set(ctx)
            return ctx
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
    base_url=_issuer_base_url(),
    oauth_resource_metadata=oauth_protected_resource_metadata()
    if settings.MCP_ENABLED and _issuer_base_url()
    else None,
    server_info={
        "name": "Flit Core MCP",
        "version": "0.1.0",
    },
)
