"""Tests for user service: update_user resets is_verified when email changes."""

import pytest

from auth.password import get_password_hash
from schemas.user import UserUpdate
from service.user import create_user, update_user


@pytest.mark.asyncio
async def test_update_email_resets_is_verified(
    test_db_session,
    sample_user_data: dict,
):
    """When user changes email to a different address, is_verified is set to False."""
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user_data["is_verified"] = True
    user = await create_user(test_db_session, user_data)
    await test_db_session.commit()

    updated = await update_user(
        test_db_session,
        user.id,
        UserUpdate(
            current_password=sample_user_data["password"],
            email="newemail@example.com",
        ),
    )
    assert updated.email == "newemail@example.com"
    assert updated.is_verified is False
