"""Boundary error taxonomy, safe messages and FastAPI exception handlers.

No handler serializes Pydantic or FastAPI error detail: those payloads embed
the offending input, which may be a transcript or raw DTMF.
"""

import logging

from fastapi import Request
from fastapi.responses import JSONResponse

from app.api.contracts import ErrorBody, ErrorCode, ErrorResponse

logger = logging.getLogger(__name__)


class ApiError(Exception):
    """Boundary failure with a stable taxonomy code and a safe message."""

    code: ErrorCode = ErrorCode.INTERNAL
    status_code: int = 500
    public_message: str = "internal error"


class AuthenticationError(ApiError):
    """The caller did not present the configured API key."""

    code = ErrorCode.AUTHORIZATION
    status_code = 401
    public_message = "authentication failed"


class ApiKeyNotConfiguredError(ApiError):
    """The service runs without the expected API key configured."""

    code = ErrorCode.INTERNAL
    status_code = 500
    public_message = "internal error"


class IdentityValidationUnavailableError(ApiError):
    """Identity data arrived but no validation integration exists yet."""

    code = ErrorCode.DEPENDENCY_UNAVAILABLE
    status_code = 503
    public_message = "identity validation is not available"


class DependencyTimeoutError(ApiError):
    """An external dependency exceeded its deadline."""

    code = ErrorCode.DEPENDENCY_TIMEOUT
    status_code = 504
    public_message = "dependency timed out"


class DependencyUnavailableError(ApiError):
    """An external dependency failed or could not be reached."""

    code = ErrorCode.DEPENDENCY_UNAVAILABLE
    status_code = 503
    public_message = "dependency is not available"


class ConversationEngineUnavailableError(ApiError):
    """No conversational engine is wired into this boundary yet."""

    code = ErrorCode.DEPENDENCY_UNAVAILABLE
    status_code = 503
    public_message = "conversation engine is not available"


def error_response(code: ErrorCode, status_code: int, message: str) -> JSONResponse:
    """Build the safe error envelope; never include request data."""
    body = ErrorResponse(error=ErrorBody(code=code, message=message))
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


async def api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Render a known boundary failure without technical detail."""
    error = exc if isinstance(exc, ApiError) else ApiError()
    return error_response(error.code, error.status_code, error.public_message)


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Reject an invalid request without echoing Pydantic error detail.

    Pydantic errors carry the offending input, so only the failure itself is
    recorded, never the payload.
    """
    logger.info("request validation failed path=%s", request.url.path)
    return error_response(ErrorCode.VALIDATION, 422, "request validation failed")


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Render an unexpected failure; log the type only, never the message."""
    logger.error("unhandled boundary error error_type=%s", type(exc).__name__)
    return error_response(ErrorCode.INTERNAL, 500, "internal error")
