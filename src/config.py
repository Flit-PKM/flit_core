from __future__ import annotations

import json
from typing import List, Literal, Optional

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from urllib.parse import quote

_DEFAULT_ALLOWED_APPS: List[dict[str, str]] = [
    {"slug": "flit", "name": "Flit"},
    {"slug": "still", "name": "Still"},
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    PROJECT_NAME: str = "Flit Core"
    ENVIRONMENT: str = "development"

    # Server Settings
    PORT: int = Field(default=8000, ge=1, le=65535, description="Server port")

    # JWT Settings - SECRET_KEY is required and must be set via environment variable
    SECRET_KEY: str = Field(..., min_length=32, description="Secret key for JWT tokens (minimum 32 characters)")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Token settings (used by connect exchange and refresh)
    OAUTH_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    OAUTH_REFRESH_TOKEN_EXPIRE_DAYS: int = 90

    # App list: fixed set of apps users can connect. Override via ALLOWED_APPS_JSON env.
    ALLOWED_APPS_JSON: Optional[str] = Field(
        default=None,
        description="JSON array of {slug, name} to override default app list, e.g. [{\"slug\":\"flit\",\"name\":\"Flit\"}]",
    )

    # Connection code flow (request-code / exchange)
    CONNECTION_CODE_EXPIRE_MINUTES: int = Field(
        default=10,
        ge=1,
        le=60,
        description="Connection code TTL in minutes",
    )
    CONNECTION_CODE_LENGTH: int = Field(
        default=8,
        ge=6,
        le=12,
        description="Connection code length (alphanumeric, readable)",
    )

    # Logging Settings
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    # CORS Settings
    CORS_ORIGINS: List[str] = Field(
        default=["http://localhost:5173"],
        description="Allowed CORS origins"
    )

    # Database backend: postgres (default) or d1 (Cloudflare D1)
    DB_BACKEND: Literal["postgres", "d1"] = Field(
        default="postgres",
        description="Database backend: postgres or d1 (Cloudflare D1)",
    )

    # PostgreSQL settings (required when DB_BACKEND=postgres)
    DB_USER: Optional[str] = Field(default=None, description="Database user (PostgreSQL)")
    DB_PASSWORD: Optional[str] = Field(default=None, description="Database password (PostgreSQL, min 8 chars)")
    DB_HOST: str = Field(default="localhost", description="Database host (PostgreSQL)")
    DB_PORT: int = Field(default=5432, ge=1, le=65535, description="Database port (PostgreSQL)")
    DB_NAME: Optional[str] = Field(default=None, description="Database name (PostgreSQL)")

    # Cloudflare D1 settings (required when DB_BACKEND=d1)
    CF_ACCOUNT_ID: Optional[str] = Field(default=None, description="Cloudflare account ID (D1)")
    CF_API_TOKEN: Optional[str] = Field(default=None, description="Cloudflare API token with D1 permissions")
    CF_DATABASE_ID: Optional[str] = Field(default=None, description="Cloudflare D1 database ID")

    # Database Connection Pool Settings (PostgreSQL only)
    DB_POOL_SIZE: int = Field(default=5, ge=1, le=100, description="Database connection pool size")
    DB_MAX_OVERFLOW: int = Field(default=10, ge=0, le=100, description="Maximum overflow connections")

    # Purge: soft-deleted rows with updated_at older than this are hard-deleted
    PURGE_SOFT_DELETED_AFTER_WEEKS: int = Field(
        default=6,
        ge=1,
        le=52,
        description="Weeks after which is_deleted rows are permanently removed",
    )

    # Cloudflare Turnstile (optional; required when POST /subscriptions is used)
    TURNSTILE_SECRET: Optional[str] = Field(
        default=None,
        description="Cloudflare Turnstile secret key for subscribe endpoint",
    )

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        """Validate that SECRET_KEY is strong enough for production."""
        if len(v) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters long")
        if v == "your-secret-key-here-change-in-production":
            raise ValueError("SECRET_KEY must be changed from default value")
        return v

    @field_validator("ENVIRONMENT")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        """Validate environment value."""
        allowed = {"development", "staging", "production", "test"}
        if v not in allowed:
            raise ValueError(f"ENVIRONMENT must be one of {allowed}")
        return v

    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level."""
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {allowed}")
        return v.upper()

    @model_validator(mode="after")
    def validate_database_backend(self) -> "Settings":
        """Require backend-specific env vars: DB_* for postgres, CF_* for d1."""
        if self.DB_BACKEND == "d1":
            missing = [k for k, v in [
                ("CF_ACCOUNT_ID", self.CF_ACCOUNT_ID),
                ("CF_API_TOKEN", self.CF_API_TOKEN),
                ("CF_DATABASE_ID", self.CF_DATABASE_ID),
            ] if not v]
            if missing:
                raise ValueError(
                    f"When DB_BACKEND=d1, the following are required: {', '.join(missing)}"
                )
        else:
            missing = [k for k, v in [
                ("DB_USER", self.DB_USER),
                ("DB_PASSWORD", self.DB_PASSWORD),
                ("DB_NAME", self.DB_NAME),
            ] if not v]
            if missing:
                raise ValueError(
                    f"When DB_BACKEND=postgres, the following are required: {', '.join(missing)}"
                )
            if self.DB_PASSWORD and len(self.DB_PASSWORD) < 8:
                raise ValueError("DB_PASSWORD must be at least 8 characters")
        return self

    @property
    def is_d1(self) -> bool:
        """True when using Cloudflare D1 backend."""
        return self.DB_BACKEND == "d1"

    def get_allowed_apps(self) -> List[dict[str, str]]:
        """Return app list from ALLOWED_APPS_JSON if set, else default."""
        if not self.ALLOWED_APPS_JSON:
            return _DEFAULT_ALLOWED_APPS
        data = json.loads(self.ALLOWED_APPS_JSON)
        if not isinstance(data, list):
            raise ValueError("ALLOWED_APPS_JSON must be a JSON array")
        for i, item in enumerate(data):
            if not isinstance(item, dict) or "slug" not in item or "name" not in item:
                raise ValueError(
                    f"ALLOWED_APPS_JSON[{i}] must be {{slug, name}}"
                )
        return data

    @property
    def DATABASE_URL(self) -> str:
        """Generate database URL from connection parameters for the active backend."""
        if self.DB_BACKEND == "d1":
            token = quote(self.CF_API_TOKEN or "", safe="")
            return f"cloudflare_d1+async://{self.CF_ACCOUNT_ID}:{token}@{self.CF_DATABASE_ID}"
        encoded_pw = quote(self.DB_PASSWORD or "", safe="")
        return f"postgresql+asyncpg://{self.DB_USER}:{encoded_pw}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"


settings = Settings()