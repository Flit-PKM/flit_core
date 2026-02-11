from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# API values for color scheme (frontend uses this to set theme)
ColorSchemeLiteral = Literal["light", "dark", "default"]


class UserBase(BaseModel):
    username: str = Field(
        ...,
        min_length=3,
        max_length=50,
        description="Username (3-50 characters)",
        examples=["johndoe", "alice_smith"]
    )
    email: EmailStr = Field(
        ...,
        description="User email address (must be valid email format)",
        examples=["user@example.com", "john.doe@company.com"]
    )
    is_active: Optional[bool] = Field(
        True,
        description="Whether the user account is active",
        examples=[True]
    )
    is_superuser: Optional[bool] = Field(
        False,
        description="Whether the user has superuser privileges",
        examples=[False]
    )
    is_verified: Optional[bool] = Field(
        False,
        description="Whether the user email has been verified",
        examples=[False]
    )
    color_scheme: Optional[ColorSchemeLiteral] = Field(
        "default",
        description="UI color scheme preference: light, dark, or default (follow system)",
        examples=["default", "light", "dark"],
    )


class UserCreate(BaseModel):
    email: EmailStr = Field(
        ...,
        description="User email address (must be valid email format)",
        examples=["user@example.com", "john.doe@company.com"]
    )
    username: Optional[str] = Field(
        None,
        min_length=3,
        max_length=50,
        description="Username (3-50 characters, auto-generated from email if not provided)",
        examples=["johndoe", None]
    )
    password: str = Field(
        ...,
        min_length=8,
        description="User password (minimum 8 characters)",
        examples=["SecurePass123!", "MyP@ssw0rd"]
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "user@example.com",
                "password": "SecurePass123!",
                "username": "johndoe"
            }
        }
    )


class UserUpdate(BaseModel):
    current_password: str = Field(
        ...,
        description="Current password (required for verification when updating user details)",
        examples=["CurrentPass123!"]
    )
    username: Optional[str] = Field(
        None,
        min_length=3,
        max_length=50,
        description="Updated username (3-50 characters, only set if changing)",
        examples=["newusername", None]
    )
    email: Optional[EmailStr] = Field(
        None,
        description="Updated email address (only set if changing)",
        examples=["newemail@example.com", None]
    )
    password: Optional[str] = Field(
        None,
        min_length=8,
        description="New password (minimum 8 characters, only set if changing password)",
        examples=["NewSecurePass123!", None]
    )
    color_scheme: Optional[ColorSchemeLiteral] = Field(
        None,
        description="UI color scheme preference: light, dark, or default (only set if changing)",
        examples=["light", "dark", "default", None],
    )


class UserSubscriptionRead(BaseModel):
    """Subscription chosen by the user (at most one per user)."""

    status: Optional[str] = Field(None, description="Subscription status (e.g. active, canceled)")
    current_period_end: Optional[str] = Field(None, description="End of current period (ISO 8601)")
    dodo_subscription_id: Optional[str] = Field(None, description="Dodo subscription ID")


class UserAccessGrantRead(BaseModel):
    """Active access-code grant: time-limited access without a subscription."""

    expires_at: str = Field(..., description="When the grant expires (ISO 8601)")
    includes_encryption: bool = Field(..., description="Whether the grant includes encryption")


class UserRead(UserBase):
    id: int = Field(..., description="Unique user identifier", examples=[1, 42])
    created_at: datetime = Field(..., description="Account creation timestamp", examples=["2024-01-15T10:30:00Z"])
    updated_at: datetime = Field(..., description="Last account update timestamp", examples=["2024-01-20T14:22:00Z"])
    subscription: Optional[UserSubscriptionRead] = Field(
        None,
        description="User's plan subscription if any (one per user)",
    )
    access_grant: Optional[UserAccessGrantRead] = Field(
        None,
        description="Active access-code grant if any (shows when it expires)",
    )
    entitlement_active: bool = Field(
        False,
        description="True when the user has an active subscription or an active access-code grant",
    )

    model_config = ConfigDict(from_attributes=True)


# Authentication schemas
class UserLogin(BaseModel):
    email: EmailStr = Field(
        ...,
        description="User email address used for login",
        examples=["user@example.com", "john.doe@company.com"]
    )
    password: str = Field(
        ...,
        description="User password",
        examples=["SecurePass123!", "MyP@ssw0rd"]
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "user@example.com",
                "password": "SecurePass123!"
            }
        }
    )


class Token(BaseModel):
    access_token: str = Field(
        ...,
        description="JWT access token for API authentication",
        examples=["eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."]
    )
    token_type: str = Field(
        "bearer",
        description="Token type, always 'bearer' for this API",
        examples=["bearer"]
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c2VyQGV4YW1wbGUuY29tIiwiZXhwIjoxNzA1NzI5NjAwfQ.signature",
                "token_type": "bearer"
            }
        }
    )


class TokenData(BaseModel):
    username: Optional[str] = Field(
        None,
        description="Username extracted from token (optional)",
        examples=["johndoe", None]
    )