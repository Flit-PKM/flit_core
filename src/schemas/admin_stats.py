"""Response model for GET /admin/stats."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AdminStatsUsers(BaseModel):
    total: int = Field(..., description="Total registered users")
    verified: int = Field(..., description="Email-verified users")
    unverified: int = Field(..., description="Not yet verified")
    new_last_24h: int = Field(..., description="Users registered in last 24 hours")
    new_last_7d: int = Field(..., description="Users registered in last 7 days")
    new_last_30d: int = Field(..., description="Users registered in last 30 days")
    active_login_last_24h: int = Field(..., description="Distinct users with last_login in last 24h")
    active_login_last_7d: int = Field(..., description="Distinct users with last_login in last 7d (WAU-style)")
    active_login_last_30d: int = Field(
        ...,
        description="Distinct users with last_login in last 30 days (MAU-style)",
    )
    unverified_stale_30d: int = Field(
        ...,
        description="Unverified users stale 30+ days (same window as default prune)",
    )


class AdminStatsFeedback(BaseModel):
    total: int
    new_last_24h: int
    new_last_7d: int


class AdminStatsSubscriptions(BaseModel):
    total: int
    new_last_24h: int
    new_last_7d: int


class AdminStatsBilling(BaseModel):
    users_with_active_plan_subscription: int = Field(
        ...,
        description="Users with plan_subscriptions.status == active",
    )


class AdminStatsRead(BaseModel):
    users: AdminStatsUsers
    feedback: AdminStatsFeedback
    subscriptions: AdminStatsSubscriptions
    billing: AdminStatsBilling
