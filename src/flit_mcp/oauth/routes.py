from __future__ import annotations

import secrets
from typing import Optional
from urllib.parse import urlencode, urlparse

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.session import get_async_session
from exceptions import AuthenticationError, ValidationError
from flit_mcp.oauth.cimd import resolve_oauth_client
from flit_mcp.oauth.metadata import (
    oauth_authorization_server_metadata,
    oauth_protected_resource_metadata,
)
from flit_mcp.scopes import normalize_requested_scope
from limiter import limiter
from routes.auth import authenticate_user
from service.mcp_oauth import (
    build_redirect_with_code,
    build_redirect_with_error,
    canonical_mcp_resource,
    create_pending_authorization,
    exchange_authorization_code,
    get_pending_by_state,
    issue_authorization_code,
    mcp_issuer,
    public_base_url,
    redirect_uri_allowed,
    refresh_mcp_access_token,
    resolve_resource_param,
    set_pending_user,
)
from service.user import create_user, get_user_by_email, touch_last_login
from auth.username_from_email import derive_username_from_email
from schemas.mcp_oauth import McpOAuthRevokeResponse, McpOAuthTokenResponse

router = APIRouter(prefix="/mcp/oauth", tags=["mcp-oauth"])

MCP_SESSION_COOKIE = "mcp_oauth_state"


def _redirect_is_localhost(redirect_uri: str) -> bool:
    host = (urlparse(redirect_uri).hostname or "").lower()
    return host in ("127.0.0.1", "localhost")


def _localhost_warning(redirect_uri: str) -> str:
    if not _redirect_is_localhost(redirect_uri):
        return ""
    return (
        '<p class="warn"><strong>Note:</strong> This app uses a localhost redirect. '
        "Only continue if you trust the application on your device.</p>"
    )


def _logo_block(logo_uri: str | None) -> str:
    if not logo_uri:
        return ""
    return f'<p><img src="{logo_uri}" alt="" style="max-height:48px" /></p>'


def _login_html(
    *,
    state: str,
    client_name: str,
    scope: str,
    resource_label: str,
    redirect_uri: str,
    logo_uri: str | None = None,
    error: str | None = None,
    google_enabled: bool,
) -> str:
    err = f'<p class="error">{error}</p>' if error else ""
    google_block = ""
    if google_enabled:
        google_url = f"/mcp/oauth/google/start?state={state}"
        google_block = f'<a class="btn secondary" href="{google_url}">Sign in with Google</a>'
    register_url = public_base_url()
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Flit MCP — Sign in</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 420px; margin: 2rem auto; }}
.error {{ color: #b91c1c; }}
.warn {{ color: #92400e; background: #fef3c7; padding: 0.75rem; border-radius: 6px; }}
.btn {{ display: block; width: 100%; padding: 0.6rem; margin-top: 0.5rem; text-align: center;
  background: #2563eb; color: white; text-decoration: none; border: none; border-radius: 6px; }}
.btn.secondary {{ background: #fff; color: #333; border: 1px solid #ccc; }}
label {{ display: block; margin-top: 0.75rem; }}
input {{ width: 100%; padding: 0.5rem; box-sizing: border-box; }}
</style></head>
<body>
<h1>Connect to Flit</h1>
{_logo_block(logo_uri)}
<p>Application <strong>{client_name}</strong> requests <code>{scope}</code> access to your Flit PKM data at <code>{resource_label}</code>.</p>
{_localhost_warning(redirect_uri)}
{err}
<form method="post" action="/mcp/oauth/login">
  <input type="hidden" name="state" value="{state}" />
  <label>Email <input type="email" name="email" required autocomplete="email" /></label>
  <label>Password <input type="password" name="password" required autocomplete="current-password" /></label>
  <button class="btn" type="submit">Sign in with email</button>
</form>
{google_block}
<p><small>No account? <a href="{register_url}">Register on Flit</a></small></p>
</body></html>"""


def _consent_html(
    *,
    state: str,
    client_name: str,
    scope: str,
    resource_label: str,
    redirect_uri: str,
    logo_uri: str | None = None,
) -> str:
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Flit MCP — Authorize</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 420px; margin: 2rem auto; }}
.warn {{ color: #92400e; background: #fef3c7; padding: 0.75rem; border-radius: 6px; }}
.btn {{ padding: 0.6rem 1.2rem; border-radius: 6px; border: none; cursor: pointer; }}
.allow {{ background: #2563eb; color: white; }}
.deny {{ background: #e5e7eb; margin-left: 0.5rem; }}
</style></head>
<body>
<h1>Authorize access</h1>
{_logo_block(logo_uri)}
<p><strong>{client_name}</strong> wants <code>{scope}</code> access to your Flit PKM data at <code>{resource_label}</code>.</p>
{_localhost_warning(redirect_uri)}
<form method="post" action="/mcp/oauth/consent" style="margin-top:1.5rem">
  <input type="hidden" name="state" value="{state}" />
  <button class="btn allow" name="action" value="allow" type="submit">Allow</button>
  <button class="btn deny" name="action" value="deny" type="submit">Deny</button>
</form>
</body></html>"""


def _html_for_pending(
    pending,
    client,
    *,
    error: str | None = None,
    google_enabled: bool | None = None,
) -> HTMLResponse:
    resource_label = pending.resource or canonical_mcp_resource()
    if pending.user_id:
        html = _consent_html(
            state=pending.state,
            client_name=client.name,
            scope=pending.scopes,
            resource_label=resource_label,
            redirect_uri=pending.redirect_uri,
            logo_uri=client.logo_uri,
        )
    else:
        html = _login_html(
            state=pending.state,
            client_name=client.name,
            scope=pending.scopes,
            resource_label=resource_label,
            redirect_uri=pending.redirect_uri,
            logo_uri=client.logo_uri,
            error=error,
            google_enabled=google_enabled
            if google_enabled is not None
            else bool(
                settings.MCP_GOOGLE_OAUTH_CLIENT_ID
                and settings.MCP_GOOGLE_OAUTH_CLIENT_SECRET
            ),
        )
    resp = HTMLResponse(html)
    resp.set_cookie(MCP_SESSION_COOKIE, pending.state, httponly=True, samesite="lax", max_age=600)
    return resp


@router.get("/authorize")
@limiter.limit("20/minute")
async def authorize(
    request: Request,
    client_id: str = Query(...),
    redirect_uri: str = Query(...),
    response_type: str = Query(...),
    state: str = Query(...),
    code_challenge: str = Query(...),
    code_challenge_method: str = Query(default="S256"),
    scope: Optional[str] = Query(None),
    resource: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_async_session),
):
    if response_type != "code":
        raise HTTPException(status_code=400, detail="Only response_type=code is supported")
    if code_challenge_method != "S256":
        raise HTTPException(status_code=400, detail="Only S256 PKCE is supported")

    try:
        resolved_resource = resolve_resource_param(resource)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    client = await resolve_oauth_client(db, client_id)
    if not client:
        raise HTTPException(status_code=400, detail="Unknown client_id")
    if not redirect_uri_allowed(redirect_uri, client):
        raise HTTPException(status_code=400, detail="Invalid redirect_uri")

    normalized_scope = normalize_requested_scope(scope)
    pending = await create_pending_authorization(
        db,
        state=state,
        client_id=client_id,
        redirect_uri=redirect_uri,
        resource=resolved_resource,
        scope=normalized_scope,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
    )

    cookie_state = request.cookies.get(MCP_SESSION_COOKIE)
    if cookie_state == state and pending.user_id:
        return _html_for_pending(pending, client)

    return _html_for_pending(pending, client)


@router.post("/login")
@limiter.limit("30/minute")
async def oauth_login(
    request: Request,
    state: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_async_session),
):
    """Browser form POST: authenticate user during MCP OAuth (HTML flow, not for API clients)."""
    pending = await get_pending_by_state(db, state)
    if not pending:
        raise HTTPException(status_code=400, detail="Invalid or expired authorization session")
    client = await resolve_oauth_client(db, pending.client_id)
    if not client:
        raise HTTPException(status_code=400, detail="Unknown client")

    try:
        user = await authenticate_user(db, email, password)
    except HTTPException:
        resp = _html_for_pending(
            pending,
            client,
            error="Incorrect email or password.",
            google_enabled=bool(
                settings.MCP_GOOGLE_OAUTH_CLIENT_ID
                and settings.MCP_GOOGLE_OAUTH_CLIENT_SECRET
            ),
        )
        resp.status_code = status.HTTP_401_UNAUTHORIZED
        return resp

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Inactive user")
    await touch_last_login(db, user.id)
    await set_pending_user(db, pending, user.id)

    return _html_for_pending(pending, client)


@router.post("/consent")
@limiter.limit("30/minute")
async def oauth_consent(
    request: Request,
    state: str = Form(...),
    action: str = Form(...),
    db: AsyncSession = Depends(get_async_session),
):
    """Browser form POST: approve or deny MCP OAuth scopes (HTML flow, not for API clients)."""
    pending = await get_pending_by_state(db, state)
    if not pending:
        raise HTTPException(status_code=400, detail="Invalid or expired authorization session")

    if action == "deny":
        return RedirectResponse(
            build_redirect_with_error(
                pending.redirect_uri, "access_denied", state
            ),
            status_code=302,
        )

    if pending.user_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    code = await issue_authorization_code(db, pending)
    return RedirectResponse(
        build_redirect_with_code(pending.redirect_uri, code, state),
        status_code=302,
    )


@router.get("/google/start")
async def google_start(state: str = Query(...)):
    if not settings.MCP_GOOGLE_OAUTH_CLIENT_ID or not settings.MCP_GOOGLE_OAUTH_CLIENT_SECRET:
        raise HTTPException(status_code=503, detail="Google login not configured for MCP")
    redirect_uri = f"{mcp_issuer()}/mcp/oauth/callback/google"
    params = {
        "client_id": settings.MCP_GOOGLE_OAUTH_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    return RedirectResponse(url, status_code=302)


@router.get("/callback/google")
async def google_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_async_session),
):
    pending = await get_pending_by_state(db, state)
    if not pending:
        raise HTTPException(status_code=400, detail="Invalid or expired authorization session")
    client = await resolve_oauth_client(db, pending.client_id)
    if not client:
        raise HTTPException(status_code=400, detail="Unknown client")

    redirect_uri = f"{mcp_issuer()}/mcp/oauth/callback/google"
    async with httpx.AsyncClient() as http:
        token_resp = await http.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.MCP_GOOGLE_OAUTH_CLIENT_ID,
                "client_secret": settings.MCP_GOOGLE_OAUTH_CLIENT_SECRET,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if token_resp.status_code != 200:
            raise HTTPException(status_code=401, detail="Google token exchange failed")
        access_token = token_resp.json().get("access_token")
        userinfo_resp = await http.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if userinfo_resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Failed to fetch Google profile")

    info = userinfo_resp.json()
    email = (info.get("email") or "").lower().strip()
    if not email:
        raise HTTPException(status_code=401, detail="Google account has no email")

    user = await get_user_by_email(db, email)
    if not user:
        user_data = {
            "email": email,
            "username": derive_username_from_email(email),
            "password_hash": None,
            "is_active": True,
            "is_verified": bool(info.get("email_verified")),
        }
        user = await create_user(db, user_data)
    elif not user.is_active:
        raise HTTPException(status_code=403, detail="Inactive user")

    await touch_last_login(db, user.id)
    await set_pending_user(db, pending, user.id)

    return _html_for_pending(pending, client)


@router.post("/token", response_model=McpOAuthTokenResponse)
@limiter.limit("60/minute")
async def token_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    form = await request.form()
    grant_type = form.get("grant_type")
    resource_raw = form.get("resource")
    resource = str(resource_raw) if resource_raw is not None else None
    if grant_type == "authorization_code":
        try:
            access_row, refresh_row = await exchange_authorization_code(
                db,
                code=str(form.get("code", "")),
                redirect_uri=str(form.get("redirect_uri", "")),
                client_id=str(form.get("client_id", "")),
                code_verifier=str(form.get("code_verifier", "")),
                resource=resource,
            )
        except ValidationError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except AuthenticationError as e:
            raise HTTPException(status_code=401, detail=str(e)) from e
        expires_in = int(
            settings.MCP_ACCESS_TOKEN_EXPIRE_MINUTES * 60
        )
        return McpOAuthTokenResponse(
            access_token=access_row.token,
            expires_in=expires_in,
            refresh_token=refresh_row.token,
            scope=access_row.scopes,
        )
    if grant_type == "refresh_token":
        try:
            access_row, refresh_row = await refresh_mcp_access_token(
                db,
                str(form.get("refresh_token", "")),
                resource=resource,
            )
        except ValidationError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except AuthenticationError as e:
            raise HTTPException(status_code=401, detail=str(e)) from e
        return McpOAuthTokenResponse(
            access_token=access_row.token,
            expires_in=int(settings.MCP_ACCESS_TOKEN_EXPIRE_MINUTES * 60),
            refresh_token=refresh_row.token,
            scope=access_row.scopes,
        )
    raise HTTPException(status_code=400, detail="Unsupported grant_type")


@router.post("/revoke", response_model=McpOAuthRevokeResponse)
async def revoke_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    form = await request.form()
    token = str(form.get("token", ""))
    from sqlalchemy import select
    from models.mcp_access_token import McpAccessToken
    from models.mcp_refresh_token import McpRefreshToken

    result = await db.execute(
        select(McpAccessToken).where(McpAccessToken.token == token)
    )
    access = result.scalar_one_or_none()
    if access:
        access.revoked = True
        await db.flush()
        return McpOAuthRevokeResponse(revoked=True)

    result = await db.execute(
        select(McpRefreshToken).where(McpRefreshToken.token == token)
    )
    refresh = result.scalar_one_or_none()
    if refresh:
        from datetime import datetime, timezone

        refresh.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await db.flush()
        return McpOAuthRevokeResponse(revoked=True)

    return McpOAuthRevokeResponse(revoked=False)


def well_known_oauth_router() -> APIRouter:
    wk = APIRouter(tags=["mcp-oauth-metadata"])

    @wk.get("/.well-known/oauth-protected-resource")
    @wk.get("/.well-known/oauth-protected-resource/mcp")
    async def protected_resource():
        return oauth_protected_resource_metadata()

    @wk.get("/.well-known/oauth-authorization-server")
    async def authorization_server():
        return oauth_authorization_server_metadata()

    return wk
