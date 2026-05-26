from __future__ import annotations

import json
from typing import List, Literal, Optional

from pydantic import Field, PrivateAttr, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from urllib.parse import quote

_DEFAULT_ALLOWED_APPS: List[dict[str, str]] = [
    {"slug": "flit", "name": "Flit"},
    {"slug": "still", "name": "Still"},
    {"slug": "mcp", "name": "MCP Agent"},
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

    # JWT Settings - SECRET_KEY is required and must be set via environment variable
    SECRET_KEY: str = Field(..., min_length=32, description="Secret key for JWT tokens (minimum 32 characters)")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Google Sign-In (optional; required for POST /auth/login-google)
    GOOGLE_OAUTH_CLIENT_ID: Optional[str] = Field(
        default=None,
        description="Google OAuth 2.0 Web client ID (audience for ID token verification on /auth/login-google)",
    )

    # Token settings (used by connect exchange and refresh)
    OAUTH_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    OAUTH_REFRESH_TOKEN_EXPIRE_DAYS: int = 90

    # Rate limiting (slowapi) for public auth endpoints; disabled in tests via env
    RATE_LIMIT_AUTH_ENABLED: bool = Field(
        default=True,
        description="When true, apply rate limits to /auth/register, /auth/login, etc.",
    )

    # App list: fixed set of apps users can connect. Override via ALLOWED_APPS_JSON env.
    ALLOWED_APPS_JSON: Optional[str] = Field(
        default=None,
        description="JSON array of {slug, name} to override default app list, e.g. [{\"slug\":\"flit\",\"name\":\"Flit\"}]",
    )

    _resolved_allowed_apps: list[dict[str, str]] = PrivateAttr()

    @model_validator(mode="after")
    def _parse_allowed_apps_json(self) -> Settings:
        raw = self.ALLOWED_APPS_JSON
        if not raw or not str(raw).strip():
            self._resolved_allowed_apps = [dict(x) for x in _DEFAULT_ALLOWED_APPS]
            return self
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"ALLOWED_APPS_JSON: invalid JSON: {e}") from e
        if not isinstance(data, list):
            raise ValueError("ALLOWED_APPS_JSON must be a JSON array")
        for i, item in enumerate(data):
            if not isinstance(item, dict) or "slug" not in item or "name" not in item:
                raise ValueError(
                    f"ALLOWED_APPS_JSON[{i}] must be {{slug, name}}"
                )
        self._resolved_allowed_apps = [
            {"slug": str(item["slug"]), "name": str(item["name"])} for item in data
        ]
        return self

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

    # Managed PostgreSQL (e.g. on Render) encrypts storage at rest by default (disks and backups).
    # The application stores note bodies as plaintext in the database.

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
        description="Optional: used for is_billing_configured when plan IDs are not set (e.g. sync gating).",
    )
    DODO_PAYMENTS_MONTHLY: Optional[str] = Field(
        default=None,
        description="Dodo product ID for monthly subscription.",
    )
    DODO_PAYMENTS_ANNUAL: Optional[str] = Field(
        default=None,
        description="Dodo product ID for annual subscription.",
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

    # Public URL (email links, MCP OAuth issuer, verify/reset redirects). Required in production.
    PUBLIC_BASE_URL: Optional[str] = Field(
        default=None,
        description=(
            "Canonical public URL of this app (e.g. https://core.flit-pkm.com). "
            "Required when ENVIRONMENT=production. In development/test, sensible defaults apply if unset."
        ),
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

    # Password reset (redirects use PUBLIC_BASE_URL via public_base_url())
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

    # MCP server (optional; /mcp and /mcp/oauth when enabled)
    MCP_ENABLED: bool = Field(
        default=False,
        description="When true, mount MCP router and OAuth authorization server",
    )
    MCP_OPENAPI_INCLUDE: bool = Field(
        default=True,
        description="Include MCP tools/resources in OpenAPI even when MCP_ENABLED=false",
    )
    MCP_GOOGLE_OAUTH_CLIENT_ID: Optional[str] = Field(
        default=None,
        description="Google OAuth Web client for MCP consent login (separate from GOOGLE_OAUTH_CLIENT_ID)",
    )
    MCP_GOOGLE_OAUTH_CLIENT_SECRET: Optional[str] = Field(
        default=None,
        description="Google OAuth client secret for MCP consent login",
    )
    MCP_ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=60,
        ge=5,
        le=1440,
        description="MCP OAuth access token TTL in minutes",
    )
    MCP_REFRESH_TOKEN_EXPIRE_DAYS: int = Field(
        default=90,
        ge=1,
        le=3650,
        description="MCP OAuth refresh token TTL in days",
    )
    MCP_AUTHORIZATION_CODE_EXPIRE_MINUTES: int = Field(
        default=10,
        ge=1,
        le=30,
        description="MCP OAuth authorization code TTL in minutes",
    )
    MCP_RATE_LIMIT_ENABLED: bool = Field(
        default=True,
        description="When true, apply rate limits to /mcp and /mcp/oauth",
    )
    MCP_RATE_LIMIT: str = Field(
        default="120/minute",
        description="slowapi limit for authenticated MCP tool/resource calls per user",
    )
    MCP_OAUTH_STATIC_CLIENTS_JSON: Optional[str] = Field(
        default=None,
        description='Optional JSON map of client_id -> {name, redirect_uris} for dev MCP clients',
    )
    MCP_OAUTH_CIMD_ENABLED: bool = Field(
        default=True,
        description="Resolve HTTPS URL client_ids via OAuth Client ID Metadata Documents (CIMD)",
    )
    MCP_OAUTH_CIMD_FETCH_TIMEOUT_SECONDS: float = Field(
        default=5.0,
        ge=1.0,
        le=30.0,
        description="Timeout for outbound CIMD metadata fetches",
    )
    MCP_OAUTH_CIMD_ALLOWED_HOST_SUFFIXES: Optional[str] = Field(
        default=None,
        description=(
            "Comma-separated host suffixes allowed for CIMD client_id URLs "
            "(empty = any HTTPS host)"
        ),
    )
    MCP_OAUTH_DCR_ENABLED: bool = Field(
        default=False,
        description="Enable Dynamic Client Registration (browser connect + POST /register)",
    )
    MCP_OAUTH_DCR_RATE_LIMIT: str = Field(
        default="10/minute",
        description="slowapi limit for POST /mcp/oauth/register",
    )
    MCP_OAUTH_DCR_DYNAMIC_CLIENT_ID: str = Field(
        default="dynamic",
        description="client_id sentinel for browser-first dynamic registration on /authorize",
    )
    MCP_CORS_REFLECT_ORIGIN: bool = Field(
        default=True,
        description=(
            "When MCP is enabled, reflect the request Origin on /mcp and MCP OAuth "
            "well-known paths so browser MCP clients need not be listed in CORS_ORIGINS"
        ),
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
        allowed = {"development", "production", "test"}
        if v not in allowed:
            raise ValueError(f"ENVIRONMENT must be one of {allowed}")
        return v

    @model_validator(mode="after")
    def validate_public_base_url_for_production(self) -> Settings:
        if self.ENVIRONMENT == "production" and not (self.PUBLIC_BASE_URL or "").strip():
            raise ValueError("PUBLIC_BASE_URL must be set when ENVIRONMENT is production")
        return self

    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level."""
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {allowed}")
        return v.upper()

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
        """Return app list from ALLOWED_APPS_JSON if set, else default (validated at startup)."""
        return list(self._resolved_allowed_apps)

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