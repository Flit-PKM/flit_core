from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import get_current_superuser
from database.session import get_async_session
from exceptions import ConflictError
from logging_config import get_logger
from models.user import User
from schemas.subscription import (
    SubscriptionDelete,
    SubscriptionRead,
    SubscriptionSubscribe,
)
from service.subscription import (
    create_subscription,
    delete_subscription_by_email,
    get_all_subscriptions,
)
from turnstile import (
    TurnstileVerificationError,
    client_ip_from_request,
    verify_turnstile_token,
)

logger = get_logger(__name__)

router = APIRouter(
    prefix="/subscriptions",
    tags=["subscriptions"],
)


@router.get("/", response_model=List[SubscriptionRead])
async def get_subscriptions(
    request: Request,
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_async_session),
    skip: int = 0,
    limit: int = 100,
    search: Optional[str] = Query(
        None, description="Case-insensitive substring match on subscriber email"
    ),
):
    """Get all subscriptions. Superuser only."""
    logger.info(
        f"GET /subscriptions/ - Superuser {current_user.id} fetching list - "
        f"Path: {request.url.path}, skip: {skip}, limit: {limit}"
    )
    subscriptions = await get_all_subscriptions(
        db, skip=skip, limit=limit, search=search
    )
    logger.info(
        f"GET /subscriptions/ - Returned {len(subscriptions)} subscriptions to superuser {current_user.id}"
    )
    return subscriptions


@router.post("/", response_model=SubscriptionRead, status_code=status.HTTP_201_CREATED)
async def subscribe(
    request: Request,
    body: SubscriptionSubscribe,
    db: AsyncSession = Depends(get_async_session),
):
    """Add an email to the subscription list. Public; requires valid Turnstile token."""
    email = body.email
    logger.info(f"POST /subscriptions/ - Subscribe attempt for email: {email}")

    try:
        await verify_turnstile_token(
            body.cf_turnstile_response, client_ip_from_request(request)
        )
    except TurnstileVerificationError as exc:
        logger.warning("Turnstile verification failed for %s: %s", email, exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Human verification failed. Please try again.",
        )

    try:
        subscription = await create_subscription(db, email)
        logger.info(f"POST /subscriptions/ - Subscribed: {subscription.id} - {email}")
        return subscription
    except ConflictError:
        raise


@router.delete("/", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe(
    request: Request,
    body: SubscriptionDelete,
    db: AsyncSession = Depends(get_async_session),
):
    """Remove an email from the subscription list. Public; requires valid Turnstile token."""
    try:
        await verify_turnstile_token(
            body.cf_turnstile_response, client_ip_from_request(request)
        )
    except TurnstileVerificationError as exc:
        logger.warning("Turnstile verification failed for unsubscribe %s: %s", body.email, exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Human verification failed. Please try again.",
        )
    await delete_subscription_by_email(db, body.email)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
