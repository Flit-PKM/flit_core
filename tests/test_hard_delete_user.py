"""One check: hard_delete removes MCP rows on SQLite."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.password import get_password_hash
from models.mcp_access_token import McpAccessToken
from models.mcp_api_key import McpApiKey
from models.user import User
from service.user import create_user
from service.user_hard_delete import hard_delete_user


@pytest.mark.asyncio
async def test_hard_delete_user_removes_mcp_rows(
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    test_db_session.add(
        McpAccessToken(
            jti="jti-1",
            token="tok",
            user_id=user.id,
            scopes="read",
            expires_at=now,
            created_at=now,
        )
    )
    test_db_session.add(
        McpApiKey(
            user_id=user.id,
            name="key",
            key_hash="hash",
            key_prefix="flit_mcp_xxxx",
            scopes="read",
            created_at=now,
        )
    )
    await test_db_session.commit()
    uid = user.id

    await hard_delete_user(test_db_session, uid)
    await test_db_session.commit()

    assert (
        await test_db_session.execute(select(User).where(User.id == uid))
    ).scalar_one_or_none() is None
    assert (
        await test_db_session.execute(
            select(McpAccessToken).where(McpAccessToken.user_id == uid)
        )
    ).scalar_one_or_none() is None
    assert (
        await test_db_session.execute(select(McpApiKey).where(McpApiKey.user_id == uid))
    ).scalar_one_or_none() is None
