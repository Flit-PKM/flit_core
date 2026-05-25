"""Tests for user service: update_user profile and password rules."""

import pytest

from auth.password import get_password_hash, verify_password
from exceptions import AuthenticationError
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
        UserUpdate(email="newemail@example.com"),
    )
    assert updated.email == "newemail@example.com"
    assert updated.is_verified is False


@pytest.mark.asyncio
async def test_update_profile_without_current_password(
    test_db_session,
    sample_user_data: dict,
):
    """Profile fields can be updated without current_password."""
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    await test_db_session.commit()

    updated = await update_user(
        test_db_session,
        user.id,
        UserUpdate(color_scheme="dark"),
    )
    assert updated.color_scheme.value == "dark"


@pytest.mark.asyncio
async def test_oauth_user_can_update_profile(
    test_db_session,
):
    """OAuth-only user (no password_hash) can update profile without a password."""
    user = await create_user(
        test_db_session,
        {
            "username": "oauthuser",
            "email": "oauth@example.com",
            "password_hash": None,
            "is_verified": True,
        },
    )
    await test_db_session.commit()

    updated = await update_user(
        test_db_session,
        user.id,
        UserUpdate(username="oauthuser2"),
    )
    assert updated.username == "oauthuser2"


@pytest.mark.asyncio
async def test_oauth_user_can_set_initial_password(
    test_db_session,
):
    """OAuth-only user can set first password without current_password."""
    user = await create_user(
        test_db_session,
        {
            "username": "oauthuser",
            "email": "oauth2@example.com",
            "password_hash": None,
            "is_verified": True,
        },
    )
    await test_db_session.commit()

    new_password = "newpassword123"
    updated = await update_user(
        test_db_session,
        user.id,
        UserUpdate(password=new_password),
    )
    assert updated.password_hash is not None
    assert verify_password(new_password, updated.password_hash)


@pytest.mark.asyncio
async def test_password_change_requires_current_password(
    test_db_session,
    sample_user_data: dict,
):
    """User with existing password must provide current_password to change it."""
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    await test_db_session.commit()

    with pytest.raises(AuthenticationError, match="Current password is required"):
        await update_user(
            test_db_session,
            user.id,
            UserUpdate(password="anotherpass123"),
        )


@pytest.mark.asyncio
async def test_password_change_rejects_wrong_current_password(
    test_db_session,
    sample_user_data: dict,
):
    """Wrong current_password is rejected when changing password."""
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    await test_db_session.commit()

    with pytest.raises(AuthenticationError, match="Current password is incorrect"):
        await update_user(
            test_db_session,
            user.id,
            UserUpdate(
                current_password="wrongpassword",
                password="anotherpass123",
            ),
        )


@pytest.mark.asyncio
async def test_password_change_with_correct_current_password(
    test_db_session,
    sample_user_data: dict,
):
    """Password change succeeds with correct current_password."""
    user_data = sample_user_data.copy()
    old_password = user_data.pop("password")
    user_data["password_hash"] = get_password_hash(old_password)
    user = await create_user(test_db_session, user_data)
    await test_db_session.commit()

    new_password = "anotherpass123"
    updated = await update_user(
        test_db_session,
        user.id,
        UserUpdate(
            current_password=old_password,
            password=new_password,
        ),
    )
    assert verify_password(new_password, updated.password_hash)
    assert not verify_password(old_password, updated.password_hash)
