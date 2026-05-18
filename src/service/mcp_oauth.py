from __future__ import annotations

import hashlib
import secrets
import base64
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode, urlparse

from jose import jwt as jose_jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.jwt import create_access_token
from config import settings
from exceptions import AuthenticationError, ValidationError
from flit_mcp.scopes import READ_WRITE_SCOPE, normalize_requested_scope
from models.mcp_access_token import McpAccessToken
from models.mcp_oauth_authorization_code import (
    McpOAuthAuthorizationCode,
    McpOAuthPendingAuthorization,
)
from models.mcp_refresh_token import McpRefreshToken

MCP_TOKEN_TYPE = "mcp"
MCP_API_KEY_PREFIX = "flit_mcp_"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _naive(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _as_utc_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def mcp_issuer() -> str:
    issuer = (settings.MCP_OAUTH_ISSUER or "").strip().rstrip("/")
    if not issuer:
        raise ValidationError("MCP_OAUTH_ISSUER is not configured")
    return issuer


def verify_pkce_challenge(
    code_verifier: str,
    code_challenge: str,
    method: str,
) -> bool:
    if method != "S256":
        return False
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return secrets.compare_digest(computed, code_challenge)


async def create_pending_authorization(
    session: AsyncSession,
    *,
    state: str,
    client_id: str,
    redirect_uri: str,
    scope: str | None,
    code_challenge: str,
    code_challenge_method: str,
) -> McpOAuthPendingAuthorization:
    scopes = normalize_requested_scope(scope)
    expires_at = _naive(
        _utcnow() + timedelta(minutes=settings.MCP_AUTHORIZATION_CODE_EXPIRE_MINUTES)
    )
    row = McpOAuthPendingAuthorization(
        state=state,
        client_id=client_id,
        redirect_uri=redirect_uri,
        scopes=scopes,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        user_id=None,
        expires_at=expires_at,
        created_at=_naive(_utcnow()),
    )
    session.add(row)
    await session.flush()
    return row


async def get_pending_by_state(
    session: AsyncSession,
    state: str,
) -> McpOAuthPendingAuthorization | None:
    result = await session.execute(
        select(McpOAuthPendingAuthorization).where(
            McpOAuthPendingAuthorization.state == state
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        return None
    if _as_utc_aware(row.expires_at) < _utcnow():
        return None
    return row


async def set_pending_user(
    session: AsyncSession,
    pending: McpOAuthPendingAuthorization,
    user_id: int,
) -> None:
    pending.user_id = user_id
    await session.flush()


async def issue_authorization_code(
    session: AsyncSession,
    pending: McpOAuthPendingAuthorization,
) -> str:
    if pending.user_id is None:
        raise AuthenticationError("User not authenticated for authorization")
    code_str = secrets.token_urlsafe(32)
    expires_at = _naive(
        _utcnow() + timedelta(minutes=settings.MCP_AUTHORIZATION_CODE_EXPIRE_MINUTES)
    )
    row = McpOAuthAuthorizationCode(
        code=code_str,
        client_id=pending.client_id,
        user_id=pending.user_id,
        redirect_uri=pending.redirect_uri,
        scopes=pending.scopes,
        code_challenge=pending.code_challenge,
        code_challenge_method=pending.code_challenge_method,
        expires_at=expires_at,
        used_at=None,
        created_at=_naive(_utcnow()),
    )
    session.add(row)
    await session.delete(pending)
    await session.flush()
    return code_str


def build_redirect_with_code(redirect_uri: str, code: str, state: str) -> str:
    sep = "&" if "?" in redirect_uri else "?"
    return f"{redirect_uri}{sep}{urlencode({'code': code, 'state': state})}"


def build_redirect_with_error(
    redirect_uri: str,
    error: str,
    state: str,
    description: str | None = None,
) -> str:
    params: dict[str, str] = {"error": error, "state": state}
    if description:
        params["error_description"] = description
    sep = "&" if "?" in redirect_uri else "?"
    return f"{redirect_uri}{sep}{urlencode(params)}"


async def exchange_authorization_code(
    session: AsyncSession,
    *,
    code: str,
    redirect_uri: str,
    client_id: str,
    code_verifier: str,
) -> tuple[McpAccessToken, McpRefreshToken]:
    result = await session.execute(
        select(McpOAuthAuthorizationCode).where(McpOAuthAuthorizationCode.code == code)
    )
    auth_code = result.scalar_one_or_none()
    if not auth_code:
        raise AuthenticationError("Invalid authorization code")
    if auth_code.used_at is not None:
        raise AuthenticationError("Authorization code already used")
    if _as_utc_aware(auth_code.expires_at) < _utcnow():
        raise AuthenticationError("Authorization code expired")
    if auth_code.client_id != client_id:
        raise AuthenticationError("Invalid client_id")
    if auth_code.redirect_uri != redirect_uri:
        raise AuthenticationError("Invalid redirect_uri")
    if not verify_pkce_challenge(
        code_verifier,
        auth_code.code_challenge,
        auth_code.code_challenge_method,
    ):
        raise AuthenticationError("Invalid code_verifier")

    auth_code.used_at = _naive(_utcnow())
    return await _issue_mcp_tokens(
        session,
        user_id=auth_code.user_id,
        scopes=auth_code.scopes,
    )


async def _issue_mcp_tokens(
    session: AsyncSession,
    *,
    user_id: int,
    scopes: str,
) -> tuple[McpAccessToken, McpRefreshToken]:
    jti = secrets.token_urlsafe(16)
    expires_delta = timedelta(minutes=settings.MCP_ACCESS_TOKEN_EXPIRE_MINUTES)
    token_data = {
        "sub": str(user_id),
        "scopes": scopes,
        "token_type": MCP_TOKEN_TYPE,
        "jti": jti,
    }
    access_jwt = create_access_token(token_data, expires_delta=expires_delta)
    expires_at = _naive(_utcnow() + expires_delta)

    refresh_str = secrets.token_urlsafe(32)
    refresh_expires = _naive(
        _utcnow() + timedelta(days=settings.MCP_REFRESH_TOKEN_EXPIRE_DAYS)
    )
    refresh_row = McpRefreshToken(
        token=refresh_str,
        user_id=user_id,
        scopes=scopes,
        expires_at=refresh_expires,
        revoked_at=None,
        created_at=_naive(_utcnow()),
    )
    session.add(refresh_row)
    await session.flush()

    access_row = McpAccessToken(
        token=access_jwt,
        user_id=user_id,
        scopes=scopes,
        jti=jti,
        expires_at=expires_at,
        refresh_token_id=refresh_row.id,
        revoked=False,
        created_at=_naive(_utcnow()),
    )
    session.add(access_row)
    await session.flush()
    return access_row, refresh_row


async def refresh_mcp_access_token(
    session: AsyncSession,
    refresh_token_str: str,
) -> tuple[McpAccessToken, McpRefreshToken]:
    result = await session.execute(
        select(McpRefreshToken).where(McpRefreshToken.token == refresh_token_str)
    )
    refresh_row = result.scalar_one_or_none()
    if not refresh_row:
        raise AuthenticationError("Invalid refresh token")
    if refresh_row.revoked_at is not None:
        raise AuthenticationError("Refresh token revoked")
    if _as_utc_aware(refresh_row.expires_at) < _utcnow():
        raise AuthenticationError("Refresh token expired")

    result = await session.execute(
        select(McpAccessToken).where(
            McpAccessToken.refresh_token_id == refresh_row.id,
            McpAccessToken.revoked.is_(False),
        )
    )
    for old_access in result.scalars().all():
        old_access.revoked = True

    refresh_row.revoked_at = _naive(_utcnow())
    return await _issue_mcp_tokens(
        session,
        user_id=refresh_row.user_id,
        scopes=refresh_row.scopes,
    )


async def validate_mcp_access_token(
    session: AsyncSession,
    token: str,
) -> tuple[int, str] | None:
    try:
        payload = jose_jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
    except jose_jwt.JWTError:
        return None
    if payload.get("token_type") != MCP_TOKEN_TYPE:
        return None
    jti = payload.get("jti")
    sub = payload.get("sub")
    scopes = payload.get("scopes")
    if not jti or not sub or not scopes:
        return None

    result = await session.execute(
        select(McpAccessToken).where(
            McpAccessToken.jti == jti,
            McpAccessToken.revoked.is_(False),
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        return None
    if _as_utc_aware(row.expires_at) < _utcnow():
        return None
    if str(row.user_id) != str(sub):
        return None
    return row.user_id, row.scopes


def redirect_uri_allowed(redirect_uri: str, client_redirect_uris: list[str]) -> bool:
    if redirect_uri in client_redirect_uris:
        return True
    parsed = urlparse(redirect_uri)
    for allowed in client_redirect_uris:
        if urlparse(allowed).netloc == parsed.netloc and urlparse(allowed).scheme == parsed.scheme:
            return True
    return False
