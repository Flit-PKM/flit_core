from __future__ import annotations

import json
from typing import List, Literal, Optional

from pydantic import Field, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from urllib.parse import quote

_DEFAULT_ALLOWED_APPS: List[dict[str, str]] = [
    {"slug": "flit", "name": "Flit"},
    {"slug": "still", "name": "Still"},
]

_DEFAULT_CORS_ORIGINS: List[str] = ["http://localhost:5173"]


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

    # CORS Settings (env: comma-separated or JSON array; empty/missing => default)
    cors_origins_env: Optional[str] = Field(
        default=None,
        description="CORS_ORIGINS env: comma-separated origins or JSON array",
        validation_alias="CORS_ORIGINS",
    )

    @computed_field
    @property
    def CORS_ORIGINS(self) -> List[str]:
        """Allowed CORS origins (from env: comma-separated or JSON; default if missing/blank)."""
        raw = self.cors_origins_env
        if not raw or not raw.strip():
            return _DEFAULT_CORS_ORIGINS.copy()
        s = raw.strip()
        if s.startswith("["):
            try:
                parsed = json.loads(s)
            except json.JSONDecodeError as e:
                raise ValueError(f"CORS_ORIGINS: invalid JSON: {e}") from e
            if not isinstance(parsed, list):
                raise ValueError("CORS_ORIGINS: JSON must be a list of strings")
            return [str(x).strip() for x in parsed if str(x).strip()]
        return [x.strip() for x in s.split(",") if x.strip()]

    # Webapp (frontend build) - path relative to project root or absolute
    WEBAPP_BUILD_DIR: str = Field(
        default="webapp_build",
        description="Directory containing frontend build (index.html, assets, etc.)",
    )

    # Database backend: postgres (default) or d1 (Cloudflare D1)
    DB_BACKEND: Literal["postgres", "d1"] = Field(
        default="postgres",
        description="Database backend: postgres or d1 (Cloudflare D1)",
    )

    # PostgreSQL settings (required when DB_BACKEND=postgres unless DATABASE_URL env is set)
    database_url_from_env: Optional[str] = Field(
        default=None,
        description="Full PostgreSQL URL (overrides DB_USER/DB_PASSWORD/DB_HOST/DB_PORT/DB_NAME when set, e.g. for Render)",
        validation_alias="DATABASE_URL",
    )
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

    # Cloudflare Turnstile (optional; required for POST /subscriptions, POST /auth/register, POST /password-reset/request when set)
    TURNSTILE_SECRET: Optional[str] = Field(
        default=None,
        description="Cloudflare Turnstile secret key (used for subscriptions, registration, password-reset request)",
    )

    # Dodo Payments (optional; required for billing endpoints)
    DODO_PAYMENTS_API_KEY: Optional[str] = Field(
        default=None,
        description="Dodo Payments API key (test or live)",
    )
    DODO_PAYMENTS_WEBHOOK_SECRET: Optional[str] = Field(
        default=None,
        description="Dodo Payments webhook signing secret for signature verification",
    )
    DODO_PAYMENTS_ENVIRONMENT: Optional[Literal["test", "live"]] = Field(
        default="test",
        description="Dodo Payments environment: test or live",
    )
    DODO_PAYMENTS_SUBSCRIPTION_PRODUCT_ID: Optional[str] = Field(
        default=None,
        description="Optional: used for is_billing_configured when the 4 plan IDs are not set (e.g. sync gating).",
    )
    # Four separate subscription products (Core+AI with optional Encryption). IDs from Dodo dashboard.
    DODO_PAYMENTS_MONTHLY_CORE_AI: Optional[str] = Field(
        default=None,
        description="Dodo product ID for Monthly Core+AI subscription.",
    )
    DODO_PAYMENTS_MONTHLY_CORE_AI_ENCRYPTION: Optional[str] = Field(
        default=None,
        description="Dodo product ID for Monthly Core+AI+Encryption subscription.",
    )
    DODO_PAYMENTS_ANNUAL_CORE_AI: Optional[str] = Field(
        default=None,
        description="Dodo product ID for Annual Core+AI subscription.",
    )
    DODO_PAYMENTS_ANNUAL_CORE_AI_ENCRYPTION: Optional[str] = Field(
        default=None,
        description="Dodo product ID for Annual Core+AI+Encryption subscription.",
    )

    # Encryption at rest (optional; when set, notes and chunk summaries are encrypted per-user)
    ENCRYPTION_MASTER_KEY: Optional[str] = Field(
        default=None,
        description="Base64-encoded 32-byte key for wrapping per-user DEKs. When unset, encryption is disabled.",
    )

    # Postmark SMTP (optional; when unset, email sending is disabled)
    POSTMARK_SMTP_TOKEN: Optional[str] = Field(
        default=None,
        description="Postmark Server API Token (used as both username and password). When unset, email is disabled.",
    )
    POSTMARK_SMTP_FROM_EMAIL: Optional[str] = Field(
        default=None,
        description="Default From address (must match verified Sender Signature in Postmark)",
    )
    POSTMARK_SMTP_FROM_NAME: Optional[str] = Field(
        default=None,
        description="Default From display name",
    )
    POSTMARK_SMTP_HOST: str = Field(
        default="smtp.postmarkapp.com",
        description="Postmark SMTP host (transactional or smtp-broadcasts.postmarkapp.com)",
    )
    POSTMARK_SMTP_PORT: int = Field(
        default=2525,
        ge=1,
        le=65535,
        description="Postmark SMTP port (2525 recommended when 25 is blocked)",
    )

    # Email verification (optional; when VERIFY_EMAIL_BASE_URL unset, send endpoint returns error)
    VERIFY_EMAIL_BASE_URL: Optional[str] = Field(
        default=None,
        description="Base URL for verification links (e.g. https://core.flit-pkm.com). Required for send.",
    )
    VERIFY_EMAIL_EXPIRE_HOURS: int = Field(
        default=24,
        ge=1,
        le=168,
        description="Verification token TTL in hours",
    )
    VERIFY_EMAIL_RESEND_COOLDOWN_MINUTES: int = Field(
        default=5,
        ge=1,
        le=60,
        description="Minimum minutes between verification email resends per user",
    )

    # Password reset (uses VERIFY_EMAIL_BASE_URL for redirect; same base as verification)
    PASSWORD_RESET_EXPIRE_HOURS: int = Field(
        default=1,
        ge=1,
        le=24,
        description="Password reset token TTL in hours",
    )
    PASSWORD_RESET_COOLDOWN_MINUTES: int = Field(
        default=5,
        ge=1,
        le=60,
        description="Minimum minutes between password reset emails per email address",
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

    @field_validator("ENCRYPTION_MASTER_KEY")
    @classmethod
    def validate_encryption_master_key(cls, v: Optional[str]) -> Optional[str]:
        """If set, ENCRYPTION_MASTER_KEY must decode to 32 bytes (base64)."""
        if not v:
            return None
        import base64
        try:
            key_bytes = base64.b64decode(v, validate=True)
        except Exception:
            raise ValueError("ENCRYPTION_MASTER_KEY must be valid base64")
        if len(key_bytes) != 32:
            raise ValueError("ENCRYPTION_MASTER_KEY must decode to 32 bytes")
        return v

    @property
    def encryption_enabled(self) -> bool:
        """True when encryption at rest is configured."""
        return bool(self.ENCRYPTION_MASTER_KEY)

    @property
    def email_configured(self) -> bool:
        """True when Postmark SMTP is configured (token set)."""
        return bool(self.POSTMARK_SMTP_TOKEN)

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
            if not self.database_url_from_env:
                missing = [k for k, v in [
                    ("DB_USER", self.DB_USER),
                    ("DB_PASSWORD", self.DB_PASSWORD),
                    ("DB_NAME", self.DB_NAME),
                ] if not v]
                if missing:
                    raise ValueError(
                        f"When DB_BACKEND=postgres, set DATABASE_URL or the following: {', '.join(missing)}"
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
        """Return database URL for the active backend (from DATABASE_URL env or built from DB_*)."""
        if self.DB_BACKEND == "d1":
            token = quote(self.CF_API_TOKEN or "", safe="")
            return f"cloudflare_d1+async://{self.CF_ACCOUNT_ID}:{token}@{self.CF_DATABASE_ID}"
        if self.database_url_from_env:
            url = self.database_url_from_env.strip()
            if url.startswith("postgres://"):
                url = "postgresql+asyncpg://" + url[len("postgres://") :]
            elif url.startswith("postgresql://") and not url.startswith("postgresql+asyncpg://"):
                url = "postgresql+asyncpg://" + url[len("postgresql://") :]
            return url
        encoded_pw = quote(self.DB_PASSWORD or "", safe="")
        return f"postgresql+asyncpg://{self.DB_USER}:{encoded_pw}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"


settings = Settings()