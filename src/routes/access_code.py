"""Access code routes: superuser creates codes, user activates."""

import logging
from typing import List

from fastapi import APIRouter, Depends, Query, status

from openapi_responses import SUPERUSER
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import get_current_active_user, get_current_superuser
from database.session import get_async_session
from exceptions import ConflictError, ValidationError
from models.user import User
from schemas.access_code import (
    AccessCodeActivateRequest,
    AccessCodeActivateResponse,
    AccessCodeAdminRead,
    AccessCodeCreateResponse,
)
from service.access_code import (
    activate_code,
    create_access_code,
    list_access_codes,
    revoke_access_code,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/access-codes",
    tags=["access-codes"],
)


@router.get("", response_model=List[AccessCodeAdminRead], responses=SUPERUSER)
async def list_access_codes_endpoint(
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_async_session),
    skip: int = Query(0, ge=0, examples=[0]),
    limit: int = Query(50, ge=1, le=500, examples=[50]),
) -> List[AccessCodeAdminRead]:
    """List access codes with pagination. Superuser only."""
    return await list_access_codes(db, skip=skip, limit=limit)


@router.post("/{code}/revoke", response_model=AccessCodeAdminRead, responses=SUPERUSER)
async def revoke_access_code_endpoint(
    code: str,
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_async_session),
) -> AccessCodeAdminRead:
    """Revoke a single-use access code by code string. Superuser only."""
    row = await revoke_access_code(db, code.strip())
    return AccessCodeAdminRead.model_validate(row)


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
