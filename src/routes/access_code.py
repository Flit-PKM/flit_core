"""Access code routes: superuser creates codes, user activates."""

import logging

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import get_current_active_user, get_current_superuser
from database.session import get_async_session
from exceptions import ConflictError, ValidationError
from models.user import User
from schemas.access_code import (
    AccessCodeActivateRequest,
    AccessCodeActivateResponse,
    AccessCodeCreateResponse,
)
from service.access_code import activate_code, create_access_code

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/access-codes",
    tags=["access-codes"],
)


@router.get(
    "/create",
    response_model=AccessCodeCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_code(
    period_weeks: int,
    includes_encryption: bool = False,
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_async_session),
) -> AccessCodeCreateResponse:
    """
    Create a new single-use access code. Superuser only.
    Query: period_weeks (1-52), includes_encryption (default false).
    """
    access_code = await create_access_code(
        db=db,
        period_weeks=period_weeks,
        includes_encryption=includes_encryption,
        created_by=current_user.id,
    )
    logger.info(
        "Access code created by superuser %s: period_weeks=%s includes_encryption=%s",
        current_user.id,
        period_weeks,
        includes_encryption,
    )
    return AccessCodeCreateResponse(
        code=access_code.code,
        period_weeks=access_code.period_weeks,
        includes_encryption=access_code.includes_encryption,
    )


@router.post(
    "/activate",
    response_model=AccessCodeActivateResponse,
    status_code=status.HTTP_200_OK,
)
async def activate(
    body: AccessCodeActivateRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> AccessCodeActivateResponse:
    """
    Activate an access code for the current user.
    Returns grant expiry and whether encryption is included.
    """
    code = (body.code or "").strip()
    if not code:
        raise ValidationError("code is required and cannot be empty")
    try:
        grant = await activate_code(db=db, code=code, user_id=current_user.id)
    except ConflictError:
        raise
    return AccessCodeActivateResponse(
        expires_at=grant.expires_at.isoformat(),
        includes_encryption=grant.includes_encryption,
    )
