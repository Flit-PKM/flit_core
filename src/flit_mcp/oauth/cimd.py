from __future__ import annotations

import ipaddress
import json
import socket
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from flit_mcp.oauth.clients import McpOAuthClient, load_static_oauth_clients
from models.mcp_oauth_cimd_cache import McpOAuthCimdCache

CIMD_MAX_BYTES = 64 * 1024
CIMD_MAX_CACHE_HOURS = 24


def is_cimd_client_id(client_id: str) -> bool:
    parsed = urlparse(client_id.strip())
    if parsed.scheme != "https":
        return False
    if not parsed.netloc:
        return False
    if not parsed.path or parsed.path == "/":
        return False
    if parsed.fragment:
        return False
    return True


def _cimd_allowed_host(host: str) -> bool:
    raw = (settings.MCP_OAUTH_CIMD_ALLOWED_HOST_SUFFIXES or "").strip()
    if not raw:
        return True
    host_lower = host.lower().rstrip(".")
    for suffix in raw.split(","):
        suffix = suffix.strip().lower().lstrip(".")
        if not suffix:
            continue
        if host_lower == suffix or host_lower.endswith("." + suffix):
            return True
    return False


def _is_private_ip(ip_str: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    return bool(
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
    )


def _resolve_host_blocks_private(hostname: str) -> bool:
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return True
    for info in infos:
        sockaddr = info[4]
        if sockaddr and _is_private_ip(sockaddr[0]):
            return True
    return False


def _cache_expiry_from_headers(headers: httpx.Headers, now: datetime) -> datetime:
    cache_control = headers.get("cache-control", "")
    max_age: int | None = None
    for part in cache_control.split(","):
        part = part.strip().lower()
        if part.startswith("max-age="):
            try:
                max_age = int(part.split("=", 1)[1])
            except ValueError:
                pass
    if max_age is not None:
        return now + timedelta(seconds=min(max_age, CIMD_MAX_CACHE_HOURS * 3600))
    expires = headers.get("expires")
    if expires:
        try:
            exp_dt = parsedate_to_datetime(expires)
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            cap = now + timedelta(hours=CIMD_MAX_CACHE_HOURS)
            return min(exp_dt.astimezone(timezone.utc), cap)
        except (TypeError, ValueError, OverflowError):
            pass
    return now + timedelta(hours=1)


def _validate_cimd_document(client_id_url: str, doc: dict[str, Any]) -> McpOAuthClient:
    doc_client_id = doc.get("client_id")
    if doc_client_id != client_id_url:
        raise ValueError("client_id in metadata does not match URL")

    name = doc.get("client_name")
    if not name or not str(name).strip():
        raise ValueError("client_name is required")

    redirect_uris = doc.get("redirect_uris")
    if not isinstance(redirect_uris, list) or not redirect_uris:
        raise ValueError("redirect_uris must be a non-empty array")

    auth_method = doc.get("token_endpoint_auth_method", "none")
    if auth_method != "none":
        raise ValueError("only token_endpoint_auth_method 'none' is supported")

    uris = [str(u) for u in redirect_uris]
    return McpOAuthClient(
        client_id=client_id_url,
        name=str(name).strip(),
        redirect_uris=uris,
        logo_uri=str(doc["logo_uri"]) if doc.get("logo_uri") else None,
        exact_redirect_match=True,
    )


async def _fetch_cimd_document(client_id_url: str) -> tuple[dict[str, Any], httpx.Headers]:
    parsed = urlparse(client_id_url)
    if not _cimd_allowed_host(parsed.hostname or ""):
        raise ValueError("client_id host not allowed by MCP_OAUTH_CIMD_ALLOWED_HOST_SUFFIXES")
    if _resolve_host_blocks_private(parsed.hostname or ""):
        raise ValueError("client_id resolves to a private or blocked address")

    timeout = settings.MCP_OAUTH_CIMD_FETCH_TIMEOUT_SECONDS
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as http:
        response = await http.get(client_id_url)
        if response.status_code != 200:
            raise ValueError(f"CIMD fetch failed with status {response.status_code}")
        if len(response.content) > CIMD_MAX_BYTES:
            raise ValueError("CIMD document too large")
        try:
            doc = response.json()
        except json.JSONDecodeError as e:
            raise ValueError("CIMD document is not valid JSON") from e
        if not isinstance(doc, dict):
            raise ValueError("CIMD document must be a JSON object")
        return doc, response.headers


async def _get_cached_cimd(
    session: AsyncSession,
    client_id_url: str,
) -> dict[str, Any] | None:
    result = await session.execute(
        select(McpOAuthCimdCache).where(McpOAuthCimdCache.client_id_url == client_id_url)
    )
    row = result.scalar_one_or_none()
    if not row:
        return None
    now = datetime.now(timezone.utc)
    exp = row.expires_at.replace(tzinfo=timezone.utc) if row.expires_at.tzinfo is None else row.expires_at
    if exp < now:
        return None
    return json.loads(row.document_json)


async def _store_cimd_cache(
    session: AsyncSession,
    client_id_url: str,
    doc: dict[str, Any],
    headers: httpx.Headers,
) -> None:
    now = datetime.now(timezone.utc)
    expires_at = _cache_expiry_from_headers(headers, now).replace(tzinfo=None)
    result = await session.execute(
        select(McpOAuthCimdCache).where(McpOAuthCimdCache.client_id_url == client_id_url)
    )
    row = result.scalar_one_or_none()
    payload = json.dumps(doc)
    if row:
        row.document_json = payload
        row.expires_at = expires_at
    else:
        session.add(
            McpOAuthCimdCache(
                client_id_url=client_id_url,
                document_json=payload,
                expires_at=expires_at,
                created_at=now.replace(tzinfo=None),
            )
        )
    await session.flush()


async def resolve_cimd_client(
    session: AsyncSession,
    client_id: str,
) -> McpOAuthClient | None:
    if not settings.MCP_OAUTH_CIMD_ENABLED:
        return None
    if not is_cimd_client_id(client_id):
        return None

    cached = await _get_cached_cimd(session, client_id)
    if cached is not None:
        try:
            return _validate_cimd_document(client_id, cached)
        except ValueError:
            return None

    try:
        doc, headers = await _fetch_cimd_document(client_id)
        client = _validate_cimd_document(client_id, doc)
        await _store_cimd_cache(session, client_id, doc, headers)
        return client
    except (ValueError, httpx.HTTPError):
        return None


async def resolve_oauth_client(
    session: AsyncSession,
    client_id: str,
) -> McpOAuthClient | None:
    static = load_static_oauth_clients().get(client_id)
    if static:
        return static
    return await resolve_cimd_client(session, client_id)
