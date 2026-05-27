from __future__ import annotations

from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.session import get_async_session
from exceptions import AuthenticationError, ValidationError
from flit_mcp.oauth.cimd import resolve_oauth_client
from flit_mcp.oauth.dcr import (
    dcr_enabled,
    is_dynamic_client_id,
    pending_display_client,
    register_oauth_client,
    registration_response_payload,
    validate_registration_request,
)
from flit_mcp.oauth.html import consent_html, login_html
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
    create_pending_authorization,
    exchange_authorization_code,
    get_pending_by_state,
    issue_authorization_code,
    mcp_issuer,
    public_base_url,
    redirect_uri_allowed,
    redirect_uri_is_valid_scheme,
    refresh_mcp_access_token,
    resolve_resource_param,
    set_pending_scopes,
    set_pending_user,
)
from service.user import create_user, get_user_by_email, touch_last_login
from auth.username_from_email import derive_username_from_email
from schemas.mcp_oauth import (
    McpOAuthClientRegistrationRequest,
    McpOAuthClientRegistrationResponse,
    McpOAuthRevokeResponse,
    McpOAuthTokenResponse,
)
from flit_mcp.oauth.clients import McpOAuthClient

router = APIRouter(prefix="/mcp/oauth", tags=["mcp-oauth"])

MCP_SESSION_COOKIE = "mcp_oauth_state"

_STATIC_DIR = Path(__file__).resolve().parent / "static"
_FLIT_LOGO_PATH = _STATIC_DIR / "flit_logo.svg"
_GOOGLE_LOGO_PATH = _STATIC_DIR / "google_logo.svg"


async def _client_for_pending(
    db: AsyncSession,
    pending,
) -> McpOAuthClient:
    if pending.dynamic_registration:
        return pending_display_client(pending)
    client = await resolve_oauth_client(db, pending.client_id)
    if not client:
        raise HTTPException(status_code=400, detail="Unknown client")
    return client


def _google_enabled() -> bool:
    return bool(
        settings.MCP_GOOGLE_OAUTH_CLIENT_ID
        and settings.MCP_GOOGLE_OAUTH_CLIENT_SECRET
    )


def _html_for_pending(
    pending,
    client,
    *,
    error: str | None = None,
    google_enabled: bool | None = None,
) -> HTMLResponse:
    if pending.user_id:
        html = consent_html(
            state=pending.state,
            client_name=client.name,
            selected_scope=pending.scopes,
            redirect_uri=pending.redirect_uri,
            logo_uri=client.logo_uri,
        )
    else:
        html = login_html(
            state=pending.state,
            client_name=client.name,
            redirect_uri=pending.redirect_uri,
            logo_uri=client.logo_uri,
            error=error,
            google_enabled=google_enabled
            if google_enabled is not None
            else _google_enabled(),
            register_url=public_base_url(),
        )
    resp = HTMLResponse(html)
    resp.set_cookie(MCP_SESSION_COOKIE, pending.state, httponly=True, samesite="lax", max_age=600)
    return resp


@router.get("/static/flit_logo.svg")
async def flit_logo_static():
    if not _FLIT_LOGO_PATH.is_file():
        raise HTTPException(status_code=404, detail="Logo not found")
    return FileResponse(
        _FLIT_LOGO_PATH,
        media_type="image/svg+xml",
        filename="flit_logo.svg",
    )


@router.get("/static/google_logo.svg")
async def google_logo_static():
    if not _GOOGLE_LOGO_PATH.is_file():
        raise HTTPException(status_code=404, detail="Logo not found")
    return FileResponse(
        _GOOGLE_LOGO_PATH,
        media_type="image/svg+xml",
        filename="google_logo.svg",
    )


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
    client_name: Optional[str] = Query(None),
    logo_uri: Optional[str] = Query(None),
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

    normalized_scope = normalize_requested_scope(scope)

    if is_dynamic_client_id(client_id):
        if not dcr_enabled():
            raise HTTPException(
                status_code=400, detail="Dynamic client registration is not enabled"
            )
        try:
            validate_registration_request(
                client_name=client_name,
                redirect_uris=[redirect_uri],
            )
        except ValidationError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        if not redirect_uri_is_valid_scheme(redirect_uri):
            raise HTTPException(status_code=400, detail="Invalid redirect_uri")

        pending = await create_pending_authorization(
            db,
            state=state,
            client_id=client_id,
            redirect_uri=redirect_uri,
            resource=resolved_resource,
            scope=normalized_scope,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            client_name=str(client_name).strip(),
            logo_uri=logo_uri,
            dynamic_registration=True,
        )
        client = pending_display_client(pending)
        return _html_for_pending(pending, client)

    client = await resolve_oauth_client(db, client_id)
    if not client:
        raise HTTPException(status_code=400, detail="Unknown client_id")
    if not redirect_uri_allowed(redirect_uri, client):
        raise HTTPException(status_code=400, detail="Invalid redirect_uri")

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
    client = await _client_for_pending(db, pending)

    try:
        user = await authenticate_user(db, email, password)
    except HTTPException:
        resp = _html_for_pending(
            pending,
            client,
            error="Incorrect email or password.",
            google_enabled=_google_enabled(),
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
    scope: str | None = Form(None),
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

    if action != "allow":
        raise HTTPException(status_code=400, detail="Invalid action")

    if scope is None or not str(scope).strip():
        raise HTTPException(status_code=400, detail="scope is required")

    await set_pending_scopes(db, pending, str(scope))

    include_client_id = pending.dynamic_registration
    if pending.dynamic_registration:
        registered = await register_oauth_client(
            db,
            client_name=pending.client_name or "Application",
            redirect_uris=[pending.redirect_uri],
            logo_uri=pending.logo_uri,
            owner_user_id=pending.user_id,
        )
        pending.client_id = registered.client_id
        pending.dynamic_registration = False
        await db.flush()

    code = await issue_authorization_code(db, pending)
    return RedirectResponse(
        build_redirect_with_code(
            pending.redirect_uri,
            code,
            state,
            client_id=pending.client_id if include_client_id else None,
        ),
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
    client = await _client_for_pending(db, pending)

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


@router.post(
    "/register",
    response_model=McpOAuthClientRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("10/minute")
async def register_client(
    request: Request,
    body: McpOAuthClientRegistrationRequest,
    db: AsyncSession = Depends(get_async_session),
):
    if not dcr_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    try:
        client = await register_oauth_client(
            db,
            client_name=body.client_name,
            redirect_uris=body.redirect_uris,
            logo_uri=body.logo_uri,
            owner_user_id=None,
        )
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    payload = registration_response_payload(client)
    return McpOAuthClientRegistrationResponse(**payload)


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
