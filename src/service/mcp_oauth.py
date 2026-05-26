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
from logging_config import get_logger
from flit_mcp.oauth.clients import McpOAuthClient
from flit_mcp.scopes import normalize_requested_scope
from models.mcp_access_token import McpAccessToken
from models.mcp_oauth_authorization_code import (
    McpOAuthAuthorizationCode,
    McpOAuthPendingAuthorization,
)
from models.mcp_refresh_token import McpRefreshToken

MCP_TOKEN_TYPE = "mcp"
MCP_API_KEY_PREFIX = "flit_mcp_"

logger = get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _naive(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _as_utc_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def public_base_url() -> str:
    """Public URL of this API (MCP OAuth issuer, email links, etc.)."""
    configured = (settings.PUBLIC_BASE_URL or "").strip().rstrip("/")
    if configured:
        return configured
    if settings.ENVIRONMENT == "development":
        return "http://127.0.0.1:8000"
    if settings.ENVIRONMENT == "test":
        return "http://testserver"
    raise ValidationError(
        "PUBLIC_BASE_URL must be set when ENVIRONMENT is production"
    )


def mcp_issuer() -> str:
    return public_base_url()


def canonical_mcp_resource() -> str:
    return f"{mcp_issuer()}/mcp"


def _normalize_resource_uri(resource: str) -> str:
    parsed = urlparse(resource.strip())
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()
    port = parsed.port
    path = parsed.path or ""
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    if port and (
        (scheme == "https" and port != 443)
        or (scheme == "http" and port != 80)
    ):
        netloc = f"{host}:{port}"
    else:
        netloc = host
    return f"{scheme}://{netloc}{path}"


def _dev_localhost_aliases_match(a: str, b: str) -> bool:
    """In dev/test, treat localhost and 127.0.0.1 as the same host for /mcp resource URIs."""
    if settings.ENVIRONMENT not in ("development", "test"):
        return False
    pa, pb = urlparse(a.strip()), urlparse(b.strip())
    if (pa.scheme or "").lower() != (pb.scheme or "").lower():
        return False
    ha, hb = (pa.hostname or "").lower(), (pb.hostname or "").lower()
    if ha == hb:
        return False
    if {ha, hb} != {"127.0.0.1", "localhost"}:
        return False

    def _default_port(parsed) -> int:
        if parsed.port is not None:
            return parsed.port
        return 443 if (parsed.scheme or "").lower() == "https" else 80

    if _default_port(pa) != _default_port(pb):
        return False

    def _norm_path(parsed) -> str:
        path = parsed.path or ""
        if path != "/" and path.endswith("/"):
            path = path.rstrip("/")
        return path

    return _norm_path(pa) == _norm_path(pb)


def resolve_resource_param(resource: str | None) -> str:
    canonical = canonical_mcp_resource()
    if not resource or not str(resource).strip():
        return canonical
    normalized = _normalize_resource_uri(str(resource))
    canonical_norm = _normalize_resource_uri(canonical)
    if normalized == canonical_norm or _dev_localhost_aliases_match(
        str(resource), canonical
    ):
        return canonical
    raise ValidationError(
        f"Invalid resource parameter; expected {canonical}"
    )


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


def redirect_uri_is_valid_scheme(redirect_uri: str) -> bool:
    parsed = urlparse(redirect_uri)
    if parsed.scheme == "https":
        return True
    if parsed.scheme == "http":
        host = (parsed.hostname or "").lower()
        return host in ("127.0.0.1", "localhost")
    return False


def redirect_uri_allowed(
    redirect_uri: str,
    client: McpOAuthClient,
) -> bool:
    if not redirect_uri_is_valid_scheme(redirect_uri):
        return False
    if redirect_uri in client.redirect_uris:
        return True
    if client.exact_redirect_match:
        return False
    parsed = urlparse(redirect_uri)
    for allowed in client.redirect_uris:
        allowed_parsed = urlparse(allowed)
        if (
            allowed_parsed.netloc == parsed.netloc
            and allowed_parsed.scheme == parsed.scheme
        ):
            return True
    return False


async def create_pending_authorization(
    session: AsyncSession,
    *,
    state: str,
    client_id: str,
    redirect_uri: str,
    resource: str,
    scope: str | None,
    code_challenge: str,
    code_challenge_method: str,
    client_name: str | None = None,
    logo_uri: str | None = None,
    dynamic_registration: bool = False,
) -> McpOAuthPendingAuthorization:
    scopes = normalize_requested_scope(scope)
    expires_at = _naive(
        _utcnow() + timedelta(minutes=settings.MCP_AUTHORIZATION_CODE_EXPIRE_MINUTES)
    )
    row = McpOAuthPendingAuthorization(
        state=state,
        client_id=client_id,
        client_name=client_name,
        logo_uri=logo_uri,
        dynamic_registration=dynamic_registration,
        redirect_uri=redirect_uri,
        resource=resource,
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


async def set_pending_scopes(
    session: AsyncSession,
    pending: McpOAuthPendingAuthorization,
    scopes: str,
) -> None:
    pending.scopes = normalize_requested_scope(scopes)
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
        resource=pending.resource,
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


def build_redirect_with_code(
    redirect_uri: str,
    code: str,
    state: str,
    *,
    client_id: str | None = None,
) -> str:
    params: dict[str, str] = {"code": code, "state": state}
    if client_id:
        params["client_id"] = client_id
    sep = "&" if "?" in redirect_uri else "?"
    return f"{redirect_uri}{sep}{urlencode(params)}"


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
    resource: str | None,
) -> tuple[McpAccessToken, McpRefreshToken]:
    resolved_resource = resolve_resource_param(resource)
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
    if auth_code.resource != resolved_resource:
        raise AuthenticationError("Invalid resource")
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
        resource=auth_code.resource,
    )


async def _issue_mcp_tokens(
    session: AsyncSession,
    *,
    user_id: int,
    scopes: str,
    resource: str | None = None,
) -> tuple[McpAccessToken, McpRefreshToken]:
    aud = canonical_mcp_resource()
    jti = secrets.token_urlsafe(16)
    expires_delta = timedelta(minutes=settings.MCP_ACCESS_TOKEN_EXPIRE_MINUTES)
    token_data = {
        "sub": str(user_id),
        "scopes": scopes,
        "token_type": MCP_TOKEN_TYPE,
        "jti": jti,
        "aud": aud,
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
    *,
    resource: str | None = None,
) -> tuple[McpAccessToken, McpRefreshToken]:
    resolved_resource = resolve_resource_param(resource)
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
        resource=resolved_resource,
    )


def _audience_matches(payload: dict, expected: str) -> bool:
    aud = payload.get("aud")
    if aud is None:
        return False

    def _aud_value_matches(token_aud: str) -> bool:
        if _normalize_resource_uri(token_aud) == _normalize_resource_uri(expected):
            return True
        return _dev_localhost_aliases_match(token_aud, expected)

    if isinstance(aud, str):
        return _aud_value_matches(aud)
    if isinstance(aud, list):
        return any(_aud_value_matches(str(a)) for a in aud)
    return False


def peek_mcp_jwt_payload(token: str) -> dict | None:
    """Decode JWT and return payload when token_type is mcp; else None."""
    try:
        payload = jose_jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={"verify_aud": False},
        )
    except jose_jwt.JWTError:
        return None
    if payload.get("token_type") != MCP_TOKEN_TYPE:
        return None
    return payload


async def _find_active_mcp_access_row(
    session: AsyncSession,
    *,
    jti: str,
    token: str,
) -> McpAccessToken | None:
    result = await session.execute(
        select(McpAccessToken).where(
            McpAccessToken.jti == jti,
            McpAccessToken.revoked.is_(False),
        )
    )
    row = result.scalar_one_or_none()
    if row:
        return row
    result = await session.execute(
        select(McpAccessToken).where(
            McpAccessToken.token == token,
            McpAccessToken.revoked.is_(False),
        )
    )
    return result.scalar_one_or_none()


async def validate_mcp_access_token(
    session: AsyncSession,
    token: str,
) -> tuple[int, str] | None:
    expected_aud = canonical_mcp_resource()
    try:
        payload = jose_jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={"verify_aud": False},
        )
    except jose_jwt.JWTError as e:
        logger.debug("MCP token validation failed: JWT decode error: %s", e)
        return None
    if payload.get("token_type") != MCP_TOKEN_TYPE:
        logger.debug(
            "MCP token validation failed: invalid token_type=%r",
            payload.get("token_type"),
        )
        return None
    if not _audience_matches(payload, expected_aud):
        logger.debug(
            "MCP token validation failed: audience mismatch aud=%r expected=%r",
            payload.get("aud"),
            expected_aud,
        )
        return None
    jti = payload.get("jti")
    sub = payload.get("sub")
    scopes = payload.get("scopes")
    if not jti or not sub or not scopes:
        logger.debug(
            "MCP token validation failed: missing claims jti=%r sub=%r scopes=%r",
            jti,
            sub,
            scopes,
        )
        return None

    row = await _find_active_mcp_access_row(session, jti=str(jti), token=token)
    if not row:
        logger.debug(
            "MCP token validation failed: no active DB row for jti=%r",
            jti,
        )
        return None
    if _as_utc_aware(row.expires_at) < _utcnow():
        logger.debug(
            "MCP token validation failed: expired at %s",
            row.expires_at,
        )
        return None
    if str(row.user_id) != str(sub):
        logger.debug(
            "MCP token validation failed: user_id mismatch row=%r sub=%r",
            row.user_id,
            sub,
        )
        return None
    return row.user_id, row.scopes
