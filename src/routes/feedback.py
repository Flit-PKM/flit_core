"""Feedback routes: public POST, superuser-only GET and DELETE."""

from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import get_current_superuser
from openapi_responses import SUPERUSER
from database.session import get_async_session
from logging_config import get_logger
from models.user import User
from schemas.feedback import (
    FeedbackCreate,
    FeedbackRead,
    FeedbackResponseCreate,
    FeedbackResponseRead,
)
from service.feedback import (
    create_feedback,
    create_feedback_response,
    delete_feedback,
    list_feedback_responses,
    list_feedbacks,
)

logger = get_logger(__name__)

router = APIRouter(
    prefix="/feedback",
    tags=["feedback"],
)


@router.post("", response_model=FeedbackRead, status_code=status.HTTP_201_CREATED)
async def create_feedback_endpoint(
    request: Request,
    body: FeedbackCreate,
    db: AsyncSession = Depends(get_async_session),
):
    """Create feedback. Public; no authentication required."""
    logger.info(f"POST /feedback - New feedback submitted")
    feedback = await create_feedback(db, body.content, body.context)
    logger.info(f"POST /feedback - Created feedback {feedback.id}")
    return feedback


@router.get("", response_model=List[FeedbackRead])
async def list_feedback_endpoint(
    request: Request,
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_async_session),
    skip: int = 0,
    limit: int = 100,
    search: Optional[str] = Query(None, description="Case-insensitive substring match on content"),
):
    """List all feedback. Superuser only."""
    logger.info(
        f"GET /feedback - Superuser {current_user.id} fetching list - "
        f"Path: {request.url.path}, skip: {skip}, limit: {limit}"
    )
    feedbacks = await list_feedbacks(db, skip=skip, limit=limit, search=search)
    logger.info(
        f"GET /feedback - Returned {len(feedbacks)} feedback items to superuser {current_user.id}"
    )
    return feedbacks


@router.get(
    "/{feedback_id}/responses",
    response_model=List[FeedbackResponseRead],
    responses=SUPERUSER,
)
async def list_feedback_responses_endpoint(
    feedback_id: int,
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_async_session),
):
    """List admin responses for a feedback thread. Superuser only."""
    return await list_feedback_responses(db, feedback_id)


@router.post(
    "/{feedback_id}/responses",
    response_model=FeedbackResponseRead,
    status_code=status.HTTP_201_CREATED,
    responses=SUPERUSER,
)
async def create_feedback_response_endpoint(
    feedback_id: int,
    body: FeedbackResponseCreate,
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_async_session),
):
    """Post an admin reply to a feedback thread. Superuser only."""
    return await create_feedback_response(
        db, feedback_id, current_user.id, body.body
    )


@router.delete("/{feedback_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_feedback_endpoint(
    request: Request,
    feedback_id: int,
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_async_session),
):
    """Delete feedback by ID. Superuser only."""
    logger.info(
        f"DELETE /feedback/{feedback_id} - Superuser {current_user.id} deleting - "
        f"Path: {request.url.path}"
    )
    await delete_feedback(db, feedback_id)
    logger.info(f"DELETE /feedback/{feedback_id} - Deleted by superuser {current_user.id}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
