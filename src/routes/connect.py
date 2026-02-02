from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import get_current_active_user
from config import settings
from database.session import get_async_session
from exceptions import ConflictError, ValidationError
from logging_config import get_logger
from models.user import User
from schemas.connect import (
    ConnectExchangeRequest,
    ConnectExchangeResponse,
    ConnectRequestCodeResponse,
)
from service.app import get_app_by_slug
from service.connected_app import create_connected_app_from_exchange
from service.connection_code import consume_connection_code, create_connection_code
from service.oauth import issue_tokens_for_connected_app

logger = get_logger(__name__)

router = APIRouter(
    prefix="/connect",
    tags=["connect"],
)


def _validate_app_slug(app_slug: str) -> None:
    """Raise ValidationError if app_slug not in allowed list."""
    app = get_app_by_slug(app_slug)
    if not app:
        raise ValidationError(f"Unknown app_slug: {app_slug}")


@router.post("/request-code", response_model=ConnectRequestCodeResponse)
async def request_code(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> ConnectRequestCodeResponse:
    """Request a connection code. User enters this code in the app to connect. Code works for any app."""
    code_row = await create_connection_code(
        session=db,
        user_id=current_user.id,
    )
    expires_in = settings.CONNECTION_CODE_EXPIRE_MINUTES * 60
    return ConnectRequestCodeResponse(
        connection_code=code_row.code,
        expires_in=expires_in,
    )


@router.post("/exchange", response_model=ConnectExchangeResponse)
async def exchange(
    body: ConnectExchangeRequest,
    db: AsyncSession = Depends(get_async_session),
) -> ConnectExchangeResponse:
    """Exchange connection code + device metadata for access and refresh tokens."""
    _validate_app_slug(body.app_slug)

    try:
        code_row = await consume_connection_code(
            session=db,
            code=body.connection_code,
        )
    except ConflictError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=e.detail or str(e),
        )
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=e.detail or str(e),
        )

    connected_app = await create_connected_app_from_exchange(
        session=db,
        user_id=code_row.user_id,
        app_slug=body.app_slug,
        device_name=body.device_name,
        platform=body.platform,
        app_version=body.app_version,
    )
    access_token, refresh_token = await issue_tokens_for_connected_app(
        session=db,
        connected_app_id=connected_app.id,
        user_id=code_row.user_id,
    )
    expires_in = int(
        (access_token.expires_at.timestamp() - access_token.created_at.timestamp())
    )
    return ConnectExchangeResponse(
        access_token=access_token.token,
        token_type="Bearer",
        expires_in=expires_in,
        refresh_token=refresh_token.token,
    )
