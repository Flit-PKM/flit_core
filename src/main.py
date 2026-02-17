import json
import logging
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.staticfiles import StaticFiles
import uvicorn


class SpaStaticFiles(StaticFiles):
    """StaticFiles that serves index.html for unknown paths (SPA client-side routing)."""

    def lookup_path(self, path: str):
        full_path, stat_result = super().lookup_path(path)
        if stat_result is None:
            return super().lookup_path("index.html")
        return full_path, stat_result

from routes.access_code import router as access_code_router
from routes.user import router as user_router, current_user_router
from routes.auth import router as auth_router
from routes.oauth import router as oauth_router
from routes.connected_app import router as connected_app_router
from routes.connect import router as connect_router
from routes.app import router as app_router
from routes.sync import router as sync_router
from routes.note import router as note_router
from routes.note_category import router as note_category_router
from routes.category import router as category_router
from routes.relationship import router as relationship_router
from routes.subscription import router as subscription_router
from routes.feedback import router as feedback_router
from routes.verify import router as verify_router
from routes.password_reset import router as password_reset_router
from routes.billing import router as billing_router
from middleware.logging import RequestLoggingMiddleware, log_exceptions_middleware
from logging_config import setup_logging
from sqlalchemy import text

from config import settings
from database.engine import engine
from exceptions import (
    BaseAppException,
    NotFoundError,
    ValidationError,
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    BusinessLogicError,
)

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)


def _format_for_log(obj: object) -> str:
    """Format a Python object for human-readable log output (indented)."""
    if obj is None:
        return "null"
    if isinstance(obj, bytes):
        try:
            return json.dumps(json.loads(obj.decode("utf-8")), indent=2, default=str)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return repr(obj)
    if isinstance(obj, (dict, list)):
        return json.dumps(obj, indent=2, default=str)
    return str(obj)


logger.info("FastAPI application starting up")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
webapp_dir = PROJECT_ROOT / settings.WEBAPP_BUILD_DIR

app = FastAPI(
    title="Flit Core",
    description="Flit PKM backend",
    version="0.1.0",
)


@app.get("/api/health")
async def health():
    """Readiness/liveness: returns 200 and optionally checks DB connectivity."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as e:
        logger.warning("Health check DB probe failed: %s", e)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unhealthy", "detail": "database unreachable"},
        )
    return {"status": "ok"}


# Exception handlers: custom app exceptions via mapping; validation and base stay explicit
_APP_EXCEPTION_HANDLERS: dict[type[BaseAppException], tuple[int, dict[str, str] | None]] = {
    NotFoundError: (status.HTTP_404_NOT_FOUND, None),
    ValidationError: (status.HTTP_400_BAD_REQUEST, None),
    AuthenticationError: (status.HTTP_401_UNAUTHORIZED, {"WWW-Authenticate": "Bearer"}),
    AuthorizationError: (status.HTTP_403_FORBIDDEN, None),
    ConflictError: (status.HTTP_409_CONFLICT, None),
    BusinessLogicError: (status.HTTP_400_BAD_REQUEST, None),
}


async def _app_exception_handler(request: Request, exc: BaseAppException) -> JSONResponse:
    """Handle custom app exceptions using status and optional headers from mapping."""
    status_code, headers = _APP_EXCEPTION_HANDLERS.get(
        type(exc), (status.HTTP_500_INTERNAL_SERVER_ERROR, None)
    )
    detail = exc.detail
    if status_code == status.HTTP_500_INTERNAL_SERVER_ERROR and settings.ENVIRONMENT == "production":
        logger.exception("Unhandled BaseAppException (detail hidden in response)")
        detail = "Internal server error"
    return JSONResponse(
        status_code=status_code,
        content={"detail": detail},
        headers=headers,
    )


for exc_cls in _APP_EXCEPTION_HANDLERS:
    app.add_exception_handler(exc_cls, _app_exception_handler)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle FastAPI request validation errors (422)."""
    errors_formatted = _format_for_log(exc.errors())
    body_raw = getattr(exc, "body", None)
    body_formatted = _format_for_log(body_raw) if body_raw is not None else "N/A"
    logger.error(
        "Request validation error - Method: %s, Path: %s, Query: %s\n  Errors:\n%s\n  Body:\n%s",
        request.method,
        request.url.path,
        request.url.query or "(none)",
        "\n".join("    " + line for line in errors_formatted.splitlines()),
        "\n".join("    " + line for line in body_formatted.splitlines()),
    )
    content: dict = {"detail": exc.errors()}
    if settings.ENVIRONMENT == "development" and hasattr(exc, "body"):
        content["body"] = exc.body
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=content,
    )


@app.exception_handler(BaseAppException)
async def base_app_exception_handler(request: Request, exc: BaseAppException):
    """Handle any other BaseAppException exceptions (fallback when not in mapping)."""
    if settings.ENVIRONMENT == "production":
        logger.exception("BaseAppException (detail hidden in response)")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error"},
        )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": exc.detail},
    )


# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Add middleware
app.middleware("http")(log_exceptions_middleware)
app.add_middleware(RequestLoggingMiddleware)

app.include_router(auth_router, prefix="/api")
app.include_router(access_code_router, prefix="/api")
app.include_router(current_user_router, prefix="/api")
app.include_router(user_router, prefix="/api")
app.include_router(oauth_router, prefix="/api")
app.include_router(connected_app_router, prefix="/api")
app.include_router(connect_router, prefix="/api")
app.include_router(app_router, prefix="/api")
app.include_router(sync_router, prefix="/api")
app.include_router(note_router, prefix="/api")
app.include_router(note_category_router, prefix="/api")
app.include_router(category_router, prefix="/api")
app.include_router(relationship_router, prefix="/api")
app.include_router(subscription_router, prefix="/api")
app.include_router(feedback_router, prefix="/api")
app.include_router(verify_router, prefix="/api")
app.include_router(password_reset_router, prefix="/api")
app.include_router(billing_router, prefix="/api")

# Mount SPA at / (after all API routes; unknown paths fall back to index.html for client-side routing)
if webapp_dir.is_dir():
    app.mount(
        "/",
        SpaStaticFiles(directory=str(webapp_dir), html=True),
        name="frontend",
    )
else:
    logger.info("Webapp build dir %s not found; SPA at / disabled", webapp_dir)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=settings.PORT)
