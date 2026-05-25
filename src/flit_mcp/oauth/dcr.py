from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from exceptions import ValidationError
from flit_mcp.oauth.clients import McpOAuthClient
from models.mcp_oauth_authorization_code import McpOAuthPendingAuthorization
from models.mcp_oauth_registered_client import McpOAuthRegisteredClient
from service.access_code import get_active_access_grant
from service.billing import SUBSCRIPTION_STATUS_ACTIVE, get_subscription_for_user, is_billing_configured
from service.mcp_oauth import redirect_uri_is_valid_scheme


def dynamic_client_id_sentinel() -> str:
    return settings.MCP_OAUTH_DCR_DYNAMIC_CLIENT_ID


def is_dynamic_client_id(client_id: str) -> bool:
    return client_id == dynamic_client_id_sentinel()


def dcr_enabled() -> bool:
    return bool(settings.MCP_OAUTH_DCR_ENABLED)


def validate_registration_request(
    *,
    client_name: str | None,
    redirect_uris: list[str],
    token_endpoint_auth_method: str | None = None,
    grant_types: list[str] | None = None,
    response_types: list[str] | None = None,
) -> None:
    if not client_name or not str(client_name).strip():
        raise ValidationError("client_name is required")
    if not redirect_uris:
        raise ValidationError("redirect_uris must be a non-empty array")
    for uri in redirect_uris:
        if not redirect_uri_is_valid_scheme(uri):
            raise ValidationError(f"Invalid redirect_uri: {uri}")
    auth_method = token_endpoint_auth_method or "none"
    if auth_method != "none":
        raise ValidationError("only token_endpoint_auth_method 'none' is supported")
    if grant_types is not None and "authorization_code" not in grant_types:
        raise ValidationError("grant_types must include authorization_code")
    if response_types is not None and "code" not in response_types:
        raise ValidationError("response_types must include code")


def _new_client_id() -> str:
    return f"mcp_reg_{secrets.token_urlsafe(16)}"


async def register_oauth_client(
    session: AsyncSession,
    *,
    client_name: str,
    redirect_uris: list[str],
    logo_uri: str | None = None,
    owner_user_id: int | None = None,
) -> McpOAuthClient:
    validate_registration_request(
        client_name=client_name,
        redirect_uris=redirect_uris,
        token_endpoint_auth_method="none",
    )
    client_id = _new_client_id()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    session.add(
        McpOAuthRegisteredClient(
            client_id=client_id,
            owner_user_id=owner_user_id,
            client_name=str(client_name).strip(),
            redirect_uris_json=json.dumps(redirect_uris),
            logo_uri=logo_uri,
            exact_redirect_match=True,
            created_at=now,
        )
    )
    await session.flush()
    return McpOAuthClient(
        client_id=client_id,
        name=str(client_name).strip(),
        redirect_uris=list(redirect_uris),
        logo_uri=logo_uri,
        exact_redirect_match=True,
    )


async def load_registered_oauth_client(
    session: AsyncSession,
    client_id: str,
) -> McpOAuthClient | None:
    result = await session.execute(
        select(McpOAuthRegisteredClient).where(
            McpOAuthRegisteredClient.client_id == client_id
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        return None
    uris = json.loads(row.redirect_uris_json)
    return McpOAuthClient(
        client_id=row.client_id,
        name=row.client_name,
        redirect_uris=uris,
        logo_uri=row.logo_uri,
        exact_redirect_match=row.exact_redirect_match,
    )


def registration_response_payload(client: McpOAuthClient) -> dict[str, Any]:
    issued_at = int(datetime.now(timezone.utc).timestamp())
    return {
        "client_id": client.client_id,
        "client_name": client.name,
        "redirect_uris": client.redirect_uris,
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "client_id_issued_at": issued_at,
        "client_secret_expires_at": 0,
    }


def pending_display_client(pending: McpOAuthPendingAuthorization) -> McpOAuthClient:
    """Build client metadata for HTML UI during a pending OAuth flow."""
    if pending.dynamic_registration:
        name = (pending.client_name or "Application").strip()
        return McpOAuthClient(
            client_id=pending.client_id,
            name=name,
            redirect_uris=[pending.redirect_uri],
            logo_uri=pending.logo_uri,
            exact_redirect_match=True,
        )
    raise ValueError("pending_display_client requires dynamic_registration pending")


async def user_has_mcp_entitlement(session: AsyncSession, user_id: int) -> bool:
    if not is_billing_configured():
        return True
    sub = await get_subscription_for_user(session, user_id)
    if sub and sub.status == SUBSCRIPTION_STATUS_ACTIVE:
        return True
    grant = await get_active_access_grant(session, user_id)
    return grant is not None
