from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from flit_mcp.auth.context import McpAuthContext, McpAuthMethod
from service.mcp_api_key import validate_mcp_api_key
from service.mcp_oauth import MCP_API_KEY_PREFIX, validate_mcp_access_token
from service.oauth import validate_access_token
from sqlalchemy import select
from models.connected_app import ConnectedApp


async def resolve_mcp_auth(
    session: AsyncSession,
    bearer_token: str | None,
) -> McpAuthContext | None:
    if not bearer_token or not bearer_token.strip():
        return None
    token = bearer_token.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()

    if token.startswith(MCP_API_KEY_PREFIX):
        result = await validate_mcp_api_key(session, token)
        if result:
            user_id, scopes = result
            return McpAuthContext(
                user_id=user_id,
                scopes_raw=scopes,
                auth_method="mcp_api_key",
            )
        return None

    mcp_result = await validate_mcp_access_token(session, token)
    if mcp_result:
        user_id, scopes = mcp_result
        return McpAuthContext(
            user_id=user_id,
            scopes_raw=scopes,
            auth_method="mcp_oauth",
        )

    connected = await validate_access_token(session, token)
    if connected:
        connected_app_id, user_id = connected
        app_result = await session.execute(
            select(ConnectedApp).where(ConnectedApp.id == connected_app_id)
        )
        app_row = app_result.scalar_one_or_none()
        if app_row and app_row.app_slug == "mcp":
            from models.oauth_access_token import OAuthAccessToken

            tok_result = await session.execute(
                select(OAuthAccessToken).where(OAuthAccessToken.token == token)
            )
            oauth_tok = tok_result.scalar_one_or_none()
            scopes = oauth_tok.scopes if oauth_tok else "read write"
            return McpAuthContext(
                user_id=user_id,
                scopes_raw=scopes,
                auth_method="connected_app_oauth",
            )

    return None
