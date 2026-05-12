"""Hard-delete a user and dependent rows (explicit order for SQLite/Postgres)."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.access_code import AccessCodeGrant
from models.category import Category
from models.chunk import Chunk
from models.connected_app import ConnectedApp
from models.connection_code import ConnectionCode
from models.feedback_response import FeedbackResponse
from models.note import Note
from models.note_category import NoteCategory
from models.notesearch import NoteSearch
from models.oauth_access_token import OAuthAccessToken
from models.oauth_refresh_token import OAuthRefreshToken
from models.plan_subscription import PlanSubscription
from models.relationship import Relationship
from models.superuser import Superuser
from models.user import User
from models.user_encryption_key import UserEncryptionKey


async def hard_delete_user(db: AsyncSession, user_id: int) -> None:
    """Remove user and owned data. Caller must enforce business rules (prune/superuser checks)."""
    await db.execute(
        delete(OAuthRefreshToken).where(OAuthRefreshToken.user_id == user_id)
    )
    await db.execute(
        delete(OAuthAccessToken).where(OAuthAccessToken.user_id == user_id)
    )
    await db.execute(delete(ConnectionCode).where(ConnectionCode.user_id == user_id))

    note_ids_result = await db.execute(select(Note.id).where(Note.user_id == user_id))
    note_ids = [row[0] for row in note_ids_result.all()]
    if note_ids:
        await db.execute(
            delete(Relationship).where(
                (Relationship.note_a_id.in_(note_ids))
                | (Relationship.note_b_id.in_(note_ids))
            )
        )
        await db.execute(delete(NoteCategory).where(NoteCategory.note_id.in_(note_ids)))
        await db.execute(delete(NoteSearch).where(NoteSearch.note_id.in_(note_ids)))
        await db.execute(delete(Chunk).where(Chunk.note_id.in_(note_ids)))
    await db.execute(delete(Note).where(Note.user_id == user_id))
    await db.execute(delete(Category).where(Category.user_id == user_id))
    await db.execute(delete(ConnectedApp).where(ConnectedApp.user_id == user_id))
    await db.execute(delete(PlanSubscription).where(PlanSubscription.user_id == user_id))
    await db.execute(delete(AccessCodeGrant).where(AccessCodeGrant.user_id == user_id))
    await db.execute(
        delete(UserEncryptionKey).where(UserEncryptionKey.user_id == user_id)
    )
    await db.execute(delete(FeedbackResponse).where(FeedbackResponse.author_user_id == user_id))
    await db.execute(delete(Superuser).where(Superuser.user_id == user_id))
    await db.execute(delete(User).where(User.id == user_id))
    await db.flush()
