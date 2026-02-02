from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
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
from turnstile import TurnstileVerificationError, verify_turnstile_token

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
):
    """Get all subscriptions. Superuser only."""
    logger.info(
        f"GET /subscriptions/ - Superuser {current_user.id} fetching list - "
        f"Path: {request.url.path}, skip: {skip}, limit: {limit}"
    )
    subscriptions = await get_all_subscriptions(db, skip=skip, limit=limit)
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
    token = body.cf_turnstile_response
    client_ip = request.headers.get("CF-Connecting-IP") or request.headers.get("X-Forwarded-For")
    if client_ip and "," in client_ip:
        client_ip = client_ip.split(",")[0].strip()
    if not client_ip and request.client:
        client_ip = request.client.host

    logger.info(f"POST /subscriptions/ - Subscribe attempt for email: {email}")

    try:
        await verify_turnstile_token(token, client_ip)
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
    body: SubscriptionDelete,
    db: AsyncSession = Depends(get_async_session),
):
    """Remove an email from the subscription list. Email must be on the list."""
    await delete_subscription_by_email(db, body.email)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
