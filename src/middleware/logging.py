import time
import logging
from typing import Callable
from fastapi import Request, Response
from fastapi.responses import JSONResponse

from logging_config import get_logger

logger = get_logger(__name__)


class RequestLoggingMiddleware:
    """
    Middleware for logging HTTP requests and responses.
    """

    def __init__(self, app: Callable):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Extract request info
        method = scope["method"]
        path = scope["path"]
        query_string = scope["query_string"].decode()

        # Create request ID for tracking
        request_id = f"{method}_{path}_{time.time()}"

        # Log request
        logger.info(
            f"Request started - ID: {request_id}, Method: {method}, "
            f"Path: {path}, Query: {query_string}"
        )

        start_time = time.time()

        # Custom send function to capture response
        response_status = None
        response_length = 0

        async def logging_send(message):
            nonlocal response_status, response_length

            if message["type"] == "http.response.start":
                response_status = message["status"]

            elif message["type"] == "http.response.body":
                response_length += len(message.get("body", b""))

            await send(message)

            # Log response when complete
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                duration = time.time() - start_time
                logger.info(
                    f"Request completed - ID: {request_id}, "
                    f"Status: {response_status}, Duration: {duration:.3f}s, "
                    f"Response Size: {response_length} bytes"
                )

        await self.app(scope, receive, logging_send)


async def log_exceptions_middleware(request: Request, call_next):
    """
    Middleware to log unhandled exceptions.
    """
    try:
        response = await call_next(request)
        return response
    except Exception as e:
        logger.error(
            f"Unhandled exception - Method: {request.method}, "
            f"Path: {request.url.path}, Error: {str(e)}",
            exc_info=True
        )
        # Return a generic error response
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"}
        )