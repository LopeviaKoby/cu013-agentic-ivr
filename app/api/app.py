"""FastAPI boundary between Cally Square and the CU013 runtime.

The boundary owns the HTTP contract, authentication, the response-contract
selector and error translation. It contains no conversational behavior:
transcript turns go through the `ConversationEngine` seam, and technical
events go through the deterministic integration service. Neither lane
executes an external side effect: the runtime creates orders and reconciles
results, and Cally Square executes.

Two temporary serializers share one domain transition:

- the legacy envelope stays byte-compatible when no contract header is sent;
- the common ``next-step-v1`` envelope is selected only by the exact header
  value, and an empty, repeated or unknown version fails closed with 400
  after authentication and before any handler runs.

Raw DTMF, document, entry date, password and email are never part of the
active contract; the closed request models reject unknown fields.
"""

import logging
import time
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, FastAPI, Header, Path, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import TypeAdapter, ValidationError

from app.api.contracts import (
    ErrorResponse,
    IntegrationEvent,
    IntegrationEventResponse,
    TranscriptTurn,
    TurnResponse,
    legacy_route_for,
)
from app.api.contracts_next_step import (
    RESPONSE_CONTRACT_HEADER,
    ResponseContract,
    next_step_response,
    select_response_contract,
)
from app.api.errors import (
    ApiError,
    ConflictOrDuplicateError,
    ConversationEngineUnavailableError,
    DependencyTimeoutError,
    DependencyUnavailableError,
    IntegrationEventsUnavailableError,
    PayloadValidationError,
    api_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from app.api.security import require_api_key
from app.conversation.engine import ConversationEngine, ConversationTurn, TurnOutcome
from app.conversation.errors import ModelTimeoutError, ModelUnavailableError
from app.session.integration import (
    IntegrationEventRejected,
    IntegrationEventService,
    NextStepIntegrationEvent,
)
from app.session.metrics import TurnMetrics
from app.session.repository import SessionPersistenceError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")

_LEGACY_EVENT_ADAPTER: TypeAdapter[IntegrationEvent] = TypeAdapter(IntegrationEvent)
_NEXT_STEP_EVENT_ADAPTER: TypeAdapter[NextStepIntegrationEvent] = TypeAdapter(
    NextStepIntegrationEvent
)


@router.post(
    "/conversations/{conversation_id}/turns",
    response_model=TurnResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Unsupported response contract."},
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
) -> Response:
    """Run one Cally Square turn after authentication, selection and validation."""
    contract = select_response_contract(request.headers.getlist(RESPONSE_CONTRACT_HEADER))
    metrics: TurnMetrics | None = getattr(request.app.state, "turn_metrics", None)
    start = time.monotonic()
    try:
        turn_id = uuid4().hex
        outcome = await _converse(request, conversation_id, turn)
        logger.info(
            "turn handled conversation_id=%s turn_id=%s next_step=%s",
            conversation_id,
            turn_id,
            outcome.next_step.value,
        )
        if contract is ResponseContract.NEXT_STEP_V1:
            envelope = next_step_response(
                message=outcome.message,
                next_step=outcome.next_step,
                command=outcome.command,
            )
            return JSONResponse(status_code=200, content=envelope.model_dump(mode="json"))
        legacy = TurnResponse(
            message=outcome.message,
            route=legacy_route_for(outcome.next_step),
            turn_id=turn_id,
            command=outcome.command,
        )
        return JSONResponse(status_code=200, content=legacy.model_dump(mode="json"))
    finally:
        if metrics is not None:
            metrics.record_segment("handler", (time.monotonic() - start) * 1000.0)


@router.post(
    "/conversations/{conversation_id}/integration-events",
    response_model=IntegrationEventResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Unsupported response contract."},
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
    _authorized: Annotated[None, Depends(require_api_key)],
    _request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None,
) -> Response:
    """Reconcile one PII-safe technical event after selecting its closed schema.

    The event vocabulary depends on the selected contract: the legacy schema
    rejects ``poll_sequence``, ``PASSWORD_PRESENTATION_RESULT`` and
    ``IDENTITY_INPUT_FAILURE``; the next-step schema requires the strict poll
    sequence. ``X-Request-ID`` is accepted as opaque HTTP correlation, never
    as an idempotency key for the side effect, and is deliberately not logged.
    """
    contract = select_response_contract(request.headers.getlist(RESPONSE_CONTRACT_HEADER))
    service: IntegrationEventService | None = getattr(request.app.state, "integration_events", None)
    if service is None:
        raise IntegrationEventsUnavailableError()
    event = await _parse_integration_event(request, contract)
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
        "integration event handled conversation_id=%s event=%s next_step=%s operation_state=%s",
        conversation_id,
        event.event,
        outcome.next_step.value,
        outcome.operation_state.value if outcome.operation_state is not None else "none",
    )
    if contract is ResponseContract.NEXT_STEP_V1:
        envelope = next_step_response(
            message=outcome.message,
            next_step=outcome.next_step,
            operation_state=outcome.operation_state,
            command=outcome.command,
        )
        return JSONResponse(status_code=200, content=envelope.model_dump(mode="json"))
    legacy = IntegrationEventResponse(
        acknowledged=True,
        operation_state=outcome.operation_state,
        directive=outcome.directive,
        message=outcome.message,
    )
    return JSONResponse(status_code=200, content=legacy.model_dump(mode="json"))


async def _parse_integration_event(
    request: Request, contract: ResponseContract
) -> IntegrationEvent | NextStepIntegrationEvent:
    """Parse the body against the closed schema the selector chose."""
    try:
        payload = await request.json()
    except ValueError as exc:
        raise PayloadValidationError() from exc
    adapter: TypeAdapter[IntegrationEvent] | TypeAdapter[NextStepIntegrationEvent]
    if contract is ResponseContract.NEXT_STEP_V1:
        adapter = _NEXT_STEP_EVENT_ADAPTER
    else:
        adapter = _LEGACY_EVENT_ADAPTER
    try:
        return adapter.validate_python(payload)
    except ValidationError as exc:
        raise PayloadValidationError() from exc


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
