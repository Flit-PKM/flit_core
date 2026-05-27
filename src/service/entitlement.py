from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import AuthorizationError
from service.access_code import get_active_access_grant
from service.billing import SUBSCRIPTION_STATUS_ACTIVE, get_subscription_for_user

ENTITLEMENT_REQUIRED_DETAIL = (
    "An active subscription or access code is required to use this feature."
)

# JSON-RPC error code when MCP usage is blocked for missing entitlement.
MCP_ENTITLEMENT_JSONRPC_CODE = -32003


async def user_has_active_entitlement(db: AsyncSession, user_id: int) -> bool:
    """True when billing is off, or user has active subscription or access-code grant."""
    from service.billing import is_billing_configured

    if not is_billing_configured():
        return True
    sub = await get_subscription_for_user(db, user_id)
    if sub and sub.status == SUBSCRIPTION_STATUS_ACTIVE:
        return True
    grant = await get_active_access_grant(db, user_id)
    return grant is not None


async def require_active_entitlement(db: AsyncSession, user_id: int) -> None:
    """Raise AuthorizationError (403) when billing is on and user lacks entitlement."""
    if await user_has_active_entitlement(db, user_id):
        return
    raise AuthorizationError(ENTITLEMENT_REQUIRED_DETAIL)
