"""One error format for the whole API.

Every error response, whatever caused it, has this JSON body:

    {"error": {"code": "not_found", "message": "Job not found", "details": null}}

- code:    stable, machine-readable; the frontend branches on it.
- message: human-readable; safe to show to the user.
- details: optional extra data, e.g. which fields failed validation.

Routes raise an AppError subclass (NotFoundError, ...) and never build error responses themselves.
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details}},
        headers=headers,
    )


# --- Error classes: raise these from routes and dependencies -------------------------------------


class AppError(Exception):
    """Base class. Subclasses only set status_code and code."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(
        self, message: str, *, details: Any = None, headers: dict[str, str] | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details
        self.headers = headers


class BadRequestError(AppError):
    status_code = 400
    code = "bad_request"


class UnauthorizedError(AppError):
    """No valid credentials: missing, expired, or tampered token."""

    status_code = 401
    code = "unauthorized"

    def __init__(self, message: str = "Authentication required", **kwargs: Any) -> None:
        # Tells clients which auth scheme to use (part of the HTTP spec for 401).
        kwargs.setdefault("headers", {"WWW-Authenticate": "Bearer"})
        super().__init__(message, **kwargs)


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"


class NotFoundError(AppError):
    """Also used for things that exist but belong to another user, so their existence
    isn't revealed."""

    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    """The request clashes with the current state, e.g. cancelling a finished job."""

    status_code = 409
    code = "conflict"


class RateLimitedError(AppError):
    status_code = 429
    code = "rate_limited"

    def __init__(self, message: str, *, retry_after_seconds: int, **kwargs: Any) -> None:
        # Retry-After is the standard header telling clients how long to wait.
        kwargs.setdefault("headers", {"Retry-After": str(retry_after_seconds)})
        kwargs.setdefault("details", {"retry_after_seconds": retry_after_seconds})
        super().__init__(message, **kwargs)


# --- Handlers: turn exceptions into the standard JSON --------------------------------------------


async def app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return error_response(exc.status_code, exc.code, exc.message, exc.details, exc.headers)


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """FastAPI raises RequestValidationError when a request doesn't match its schema."""
    assert isinstance(exc, RequestValidationError)
    details = []
    for err in exc.errors():
        # loc looks like ("body", "query") or ("path", "job_id"): split where from which field.
        location, *field_path = err["loc"]
        details.append(
            {
                "location": location,  # "body", "query", "path", or "header"
                "field": ".".join(str(part) for part in field_path) or None,
                "message": err["msg"],
                "type": err["type"],
            }
        )
    # The submitted values are deliberately not echoed back; they may contain secrets.
    return error_response(422, "validation_error", "Invalid request", details)


HTTP_STATUS_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    429: "rate_limited",
}


async def http_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """FastAPI/Starlette's own errors, e.g. 404 for an unknown URL, 405 for a wrong method."""
    assert isinstance(exc, StarletteHTTPException)
    code = HTTP_STATUS_CODES.get(exc.status_code, "http_error")
    message = exc.detail if isinstance(exc.detail, str) else "Request failed"
    # Keep headers such as Allow (sent with 405) that tell the client what to do.
    return error_response(exc.status_code, code, message, headers=exc.headers)


class UnhandledErrorMiddleware:
    """Safety net for unexpected exceptions (bugs, database down, ...).

    Logs the full error for us and returns a generic 500 to the client, so stack traces, SQL,
    and file paths never leak. It is middleware rather than an exception handler because
    FastAPI runs Exception handlers outside every other middleware, so their 500s would lack
    CORS headers and the browser would hide the response from the frontend.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            logger.exception("Unhandled error on %s %s", scope["method"], scope["path"])
            if response_started:
                # Part of a response (e.g. a stream) was already sent; nothing clean to do.
                raise
            response = error_response(500, "internal_error", "Something went wrong")
            await response(scope, receive, send)


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
