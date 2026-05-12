"""Request/response for POST /users/prune."""

from pydantic import BaseModel, Field


class UserPruneRequest(BaseModel):
    inactive_for_days: int = Field(
        30,
        ge=7,
        le=365,
        description="Users must be unverified and not seen since this many days",
    )
    dry_run: bool = Field(
        True,
        description="If true, only count and sample matches without deleting",
    )


class UserPruneResponse(BaseModel):
    matched_count: int
    deleted_count: int
    sample_user_ids: list[int] = Field(default_factory=list)
