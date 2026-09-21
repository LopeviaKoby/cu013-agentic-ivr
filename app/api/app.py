"""FastAPI boundary between Cally Square and the CU013 runtime.

The boundary owns the HTTP contract, authentication and error translation.
It contains no conversational behavior: transcript turns go through the
`ConversationEngine` seam, and technical events go through the deterministic
integration service. Neither lane executes an external side effect: the
runtime creates orders and reconciles results, and Cally Square executes.

Raw DTMF, document, birth date, password and email are never part of the
active contract; the closed request models reject unknown fields.
"""

import logging
import time
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, FastAPI, Header, Path, Request
from fastapi.exceptions import RequestValidationError

from app.api.contracts import (
    ErrorResponse,
    IntegrationEvent,
    IntegrationEventResponse,
    TranscriptTurn,
    TurnResponse,
)
from app.api.errors import (
    ApiError,
    ConflictOrDuplicateError,
    ConversationEngineUnavailableError,
    DependencyTimeoutError,
    DependencyUnavailableError,
    IntegrationEventsUnavailableError,
    api_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from app.api.security import require_api_key
from app.conversation.engine import ConversationEngine, ConversationTurn, TurnOutcome
from app.conversation.errors import ModelTimeoutError, ModelUnavailableError
from app.session.integration import IntegrationEventRejected, IntegrationEventService
from app.session.metrics import TurnMetrics
from app.session.repository import SessionPersistenceError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")


@router.post(
    "/conversations/{conversation_id}/turns",
    response_model=TurnResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Missing or invalid X-API-Key."},
        422: {"model": ErrorResponse, "description": "Invalid request payload."},
        500: {"model": ErrorResponse, "description": "Unexpected failure or unconfigured API key."},
        503: {"model": ErrorResponse, "description": "Dependency not available."},
        504: {"model": ErrorResponse, "description": "Dependency timed out."},
    },
)
async def handle_turn(
    request: Request,
    conversation_id: Annotated[str, Path(min_length=1)],
    turn: TranscriptTurn,
    _authorized: Annotated[None, Depends(require_api_key)],
) -> TurnResponse:
    """Run one Cally Square turn after authentication and validation."""
    metrics: TurnMetrics | None = getattr(request.app.state, "turn_metrics", None)
    start = time.monotonic()
    try:
        turn_id = uuid4().hex
        outcome = await _converse(request, conversation_id, turn)
        logger.info(
            "turn handled conversation_id=%s turn_id=%s route=%s",
            conversation_id,
            turn_id,
            outcome.route.value,
        )
        return TurnResponse(
            message=outcome.message,
            route=outcome.route,
            turn_id=turn_id,
            command=outcome.command,
        )
    finally:
        if metrics is not None:
            metrics.record_segment("handler", (time.monotonic() - start) * 1000.0)


@router.post(
    "/conversations/{conversation_id}/integration-events",
    response_model=IntegrationEventResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Missing or invalid X-API-Key."},
        409: {"model": ErrorResponse, "description": "Event not correlatable."},
        422: {"model": ErrorResponse, "description": "Invalid request payload."},
        500: {"model": ErrorResponse, "description": "Unexpected failure or unconfigured API key."},
        503: {"model": ErrorResponse, "description": "Dependency not available."},
    },
)
async def handle_integration_event(
    request: Request,
    conversation_id: Annotated[str, Path(min_length=1)],
    event: IntegrationEvent,
    _authorized: Annotated[None, Depends(require_api_key)],
    _request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None,
) -> IntegrationEventResponse:
    """Reconcile one PII-safe technical event; never calls the model.

    ``X-Request-ID`` is accepted as opaque HTTP correlation, never as an
    idempotency key for the side effect, and is deliberately not logged.
    """
    service: IntegrationEventService | None = getattr(request.app.state, "integration_events", None)
    if service is None:
        raise IntegrationEventsUnavailableError()
    try:
        outcome = await service.handle_event(conversation_id, event)
    except IntegrationEventRejected as exc:
        logger.info(
            "integration event rejected conversation_id=%s event=%s reason=%s",
            conversation_id,
            event.event,
            exc.reason,
        )
        raise ConflictOrDuplicateError() from exc
    except SessionPersistenceError as exc:
        raise DependencyUnavailableError() from exc
    logger.info(
        "integration event handled conversation_id=%s event=%s directive=%s operation_state=%s",
        conversation_id,
        event.event,
        outcome.directive.value,
        outcome.operation_state.value if outcome.operation_state is not None else "none",
    )
    return IntegrationEventResponse(
        acknowledged=True,
        operation_state=outcome.operation_state,
        directive=outcome.directive,
        message=outcome.message,
    )


async def _converse(request: Request, conversation_id: str, turn: TranscriptTurn) -> TurnOutcome:
    """Dispatch one validated transcript to the conversational seam."""
    engine: ConversationEngine | None = request.app.state.conversation_engine
    if engine is None:
        raise ConversationEngineUnavailableError()
    try:
        return await engine.handle_turn(
            ConversationTurn(
                conversation_id=conversation_id,
                transcript=turn.transcript,
                asr_confidence=turn.asr_confidence,
            )
        )
    except ModelTimeoutError as exc:
        raise DependencyTimeoutError() from exc
    except ModelUnavailableError as exc:
        raise DependencyUnavailableError() from exc


def create_app(
    engine: ConversationEngine | None = None,
    integration_events: IntegrationEventService | None = None,
) -> FastAPI:
    """Build the boundary with the conversational and technical seams.

    With no engine a transcript turn fails safely instead of faking a
    conversation; with no integration service a technical event fails safely
    instead of pretending to reconcile external truth.
    """
    app = FastAPI(title="CU013 Cally Square boundary", version="0.2.0")
    app.state.conversation_engine = engine
    app.state.integration_events = integration_events
    app.include_router(router)
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
    return app
