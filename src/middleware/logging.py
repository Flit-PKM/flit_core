import time
import uuid
from typing import Callable

from fastapi import Request
from starlette.datastructures import MutableHeaders

from logging_config import get_logger

logger = get_logger(__name__)


class RequestLoggingMiddleware:
    """
    Middleware for logging HTTP requests and responses.
    Assigns a UUID request_id to scope state and adds X-Request-ID on the response.
    """

    def __init__(self, app: Callable):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope["method"]
        path = scope["path"]
        query_string = scope["query_string"].decode()

        request_id = str(uuid.uuid4())
        scope.setdefault("state", {})["request_id"] = request_id

        logger.info(
            "Request started - ID: %s, Method: %s, Path: %s, Query: %s",
            request_id,
            method,
            path,
            query_string,
        )

        start_time = time.time()
        response_status = None
        response_length = 0

        async def logging_send(message):
            nonlocal response_status, response_length

            if message["type"] == "http.response.start":
                response_status = message["status"]
                headers = MutableHeaders(scope=message)
                if "x-request-id" not in headers:
                    headers.append("x-request-id", request_id)

            elif message["type"] == "http.response.body":
                response_length += len(message.get("body", b""))

            await send(message)

            if message["type"] == "http.response.body" and not message.get("more_body", False):
                duration = time.time() - start_time
                logger.info(
                    "Request completed - ID: %s, Status: %s, Duration: %.3fs, "
                    "Response Size: %s bytes",
                    request_id,
                    response_status,
                    duration,
                    response_length,
                )

        await self.app(scope, receive, logging_send)


async def log_exceptions_middleware(request: Request, call_next):
    """
    Log unhandled exceptions and re-raise so FastAPI exception handlers can run.
    """
    try:
        return await call_next(request)
    except Exception as e:
        rid = getattr(request.state, "request_id", None)
        logger.error(
            "Unhandled exception - ID: %s Method: %s Path: %s Error: %s",
            rid,
            request.method,
            request.url.path,
            str(e),
            exc_info=True,
        )
        raise
