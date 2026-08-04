"""One check: newsletter is not marked SENT when every delivery fails."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from auth.password import get_password_hash
from exceptions import ValidationError
from models.newsletter_campaign import NewsletterStatus
from service.newsletter_campaign import create_campaign, send_campaign_now
from service.subscription import create_subscription
from service.user import create_user


@pytest.mark.asyncio
async def test_send_campaign_fails_when_all_emails_fail(
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    await create_subscription(test_db_session, "list@example.com")
    campaign = await create_campaign(
        test_db_session,
        subject="Hi",
        body_text="Body",
        body_html=None,
        created_by=user.id,
    )
    await test_db_session.commit()

    with patch(
        "service.newsletter_campaign.send_email",
        new_callable=AsyncMock,
        return_value=False,
    ):
        with pytest.raises(ValidationError, match="Failed to deliver"):
            await send_campaign_now(test_db_session, campaign.id)

    await test_db_session.refresh(campaign)
    assert campaign.status == NewsletterStatus.DRAFT.value
    assert campaign.sent_at is None
