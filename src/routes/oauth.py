from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_async_session
from logging_config import get_logger
from schemas.oauth import RevokeRequest, TokenRequest, TokenResponse
from service.oauth import refresh_access_token, revoke_token

logger = get_logger(__name__)

router = APIRouter(
    prefix="/oauth",
    tags=["oauth"],
)


@router.post("/token", response_model=TokenResponse)
async def token(
    request: TokenRequest,
    db: AsyncSession = Depends(get_async_session),
) -> TokenResponse:
    """OAuth 2 token endpoint. Supports grant_type=refresh_token only."""
    if request.grant_type != "refresh_token":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported grant_type. Use refresh_token.",
        )
    if not request.refresh_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="refresh_token is required",
        )

    new_access_token, refresh_token = await refresh_access_token(
        session=db,
        refresh_token_str=request.refresh_token,
    )
    expires_in = int(
        new_access_token.expires_at.timestamp()
        - new_access_token.created_at.timestamp()
    )
    return TokenResponse(
        access_token=new_access_token.token,
        token_type="Bearer",
        expires_in=expires_in,
        refresh_token=refresh_token.token,
        scope=new_access_token.scopes,
    )


@router.post("/revoke")
async def revoke(
    request: RevokeRequest,
    db: AsyncSession = Depends(get_async_session),
):
    """Revoke an access or refresh token."""
    await revoke_token(
        session=db,
        token=request.token,
        token_type_hint=request.token_type_hint,
    )
    return {"status": "revoked"}
