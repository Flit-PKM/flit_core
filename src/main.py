import json
import logging

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
import uvicorn

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
from middleware.logging import RequestLoggingMiddleware, log_exceptions_middleware
from logging_config import setup_logging
from config import settings
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

app = FastAPI(
    title="Flit Core",
    description="Flit PKM backend",
    version="0.1.0",
)


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
    return JSONResponse(
        status_code=status_code,
        content={"detail": exc.detail},
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
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": exc.errors(), "body": exc.body if hasattr(exc, 'body') else None},
    )


@app.exception_handler(BaseAppException)
async def base_app_exception_handler(request: Request, exc: BaseAppException):
    """Handle any other BaseAppException exceptions."""
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

app.include_router(auth_router)
app.include_router(current_user_router)
app.include_router(user_router)
app.include_router(oauth_router)
app.include_router(connected_app_router)
app.include_router(connect_router)
app.include_router(app_router)
app.include_router(sync_router)
app.include_router(note_router)
app.include_router(note_category_router)
app.include_router(category_router)
app.include_router(relationship_router)
app.include_router(subscription_router)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
