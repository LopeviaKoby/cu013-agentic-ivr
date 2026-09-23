"""Boundary error taxonomy, safe messages and FastAPI exception handlers.

No handler serializes Pydantic or FastAPI error detail: those payloads embed
the offending input, which may be a transcript or raw DTMF. Telemetry emits
only closed event names, the selected lane and response contract, the HTTP
status and the (location, type) projection of a validation failure; the
public responses keep their contractual taxonomy unchanged.
"""

import logging

from fastapi import Request
from fastapi.responses import JSONResponse

from app.api.contracts import ErrorBody, ErrorCode, ErrorResponse
from app.observability import APP_LOGGER_NAME, format_validation_facts, validation_facts

logger = logging.getLogger(APP_LOGGER_NAME)


def _lane(request: Request) -> str:
    """Closed lane value; falls back to the path suffix, never the full path.

    A body rejected before the handler runs (dependency-solved validation)
    still knows which endpoint it hit without logging any identifier.
    """
    lane = getattr(request.state, "lane", None)
    if isinstance(lane, str):
        return lane
    path = request.url.path
    if path.endswith("/turns"):
        return "turns"
    if path.endswith("/integration-events"):
        return "integration_events"
    return "unknown"


def _response_contract(request: Request) -> str:
    return str(getattr(request.state, "response_contract", "unknown"))


def _log_http_result(request: Request, status_code: int) -> None:
    logger.info(
        "http_result lane=%s response_contract=%s http_status=%d",
        _lane(request),
        _response_contract(request),
        status_code,
    )


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


class IntegrationEventsUnavailableError(ApiError):
    """No technical integration-events service is wired into this boundary."""

    code = ErrorCode.DEPENDENCY_UNAVAILABLE
    status_code = 503
    public_message = "integration events are not available"


class ConflictOrDuplicateError(ApiError):
    """The event cannot be correlated with the durable session or operation."""

    code = ErrorCode.CONFLICT_OR_DUPLICATE
    status_code = 409
    public_message = "event cannot be correlated with the conversation"


class UnsupportedResponseContractError(ApiError):
    """The response-contract selector is empty, repeated or unknown."""

    code = ErrorCode.UNSUPPORTED_RESPONSE_CONTRACT
    status_code = 400
    public_message = "unsupported response contract"


class PayloadValidationError(ApiError):
    """The selected closed request contract rejected the payload.

    Used when the body is parsed after the contract selector; it renders the
    same safe validation envelope and never echoes the payload. It carries
    only the already-sanitized (location, type) facts, never the original
    exception.
    """

    code = ErrorCode.VALIDATION
    status_code = 422
    public_message = "request validation failed"

    def __init__(self, facts: tuple[tuple[str, str], ...] = ()) -> None:
        super().__init__("request validation failed")
        self.facts = facts


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
    if isinstance(error, PayloadValidationError):
        logger.info(
            "request_validation_failed lane=%s facts=%s",
            _lane(request),
            format_validation_facts(error.facts),
        )
    _log_http_result(request, error.status_code)
    return error_response(error.code, error.status_code, error.public_message)


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Reject an invalid request without echoing Pydantic error detail.

    Pydantic errors carry the offending input, so only the closed
    (location, type) facts are recorded, never the payload.
    """
    logger.info(
        "request_validation_failed lane=%s facts=%s",
        _lane(request),
        format_validation_facts(validation_facts(exc)),
    )
    _log_http_result(request, 422)
    return error_response(ErrorCode.VALIDATION, 422, "request validation failed")


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Render an unexpected failure; log the type only, never the message."""
    logger.error("unhandled boundary error error_type=%s", type(exc).__name__)
    _log_http_result(request, 500)
    return error_response(ErrorCode.INTERNAL, 500, "internal error")
