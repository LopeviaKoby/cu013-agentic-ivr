"""FastAPI boundary between Cally Square and the CU013 runtime.

The boundary owns the HTTP contract, authentication and error translation.
It contains no conversational behavior: transcript turns go through the
`ConversationEngine` seam, and raw DTMF events terminate safely until the
identity-validation integration exists.
"""

import logging
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, FastAPI, Path, Request
from fastapi.exceptions import RequestValidationError

from app.api.contracts import ErrorResponse, IdentityDataTurn, TurnRequest, TurnResponse
from app.api.errors import (
    ApiError,
    ConversationEngineUnavailableError,
    IdentityValidationUnavailableError,
    api_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from app.api.security import require_api_key
from app.conversation.engine import ConversationEngine, ConversationTurn, TurnOutcome

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")


@router.post(
    "/conversations/{conversation_id}/turns",
    response_model=TurnResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Missing or invalid X-API-Key."},
        422: {"model": ErrorResponse, "description": "Invalid request payload."},
        500: {"model": ErrorResponse, "description": "Unexpected failure or unconfigured API key."},
        503: {"model": ErrorResponse, "description": "Dependency not available yet."},
    },
)
async def handle_turn(
    request: Request,
    conversation_id: Annotated[str, Path(min_length=1)],
    turn: TurnRequest,
    _authorized: Annotated[None, Depends(require_api_key)],
) -> TurnResponse:
    """Run one Cally Square turn after authentication and validation."""
    turn_id = uuid4().hex
    outcome = await _converse(request, conversation_id, turn)
    logger.info(
        "turn handled conversation_id=%s turn_id=%s route=%s",
        conversation_id,
        turn_id,
        outcome.route.value,
    )
    return TurnResponse(message=outcome.message, route=outcome.route, turn_id=turn_id)


async def _converse(request: Request, conversation_id: str, turn: TurnRequest) -> TurnOutcome:
    """Dispatch one validated request to the conversational seam.

    Raw DTMF never reaches the engine: an IDENTITY_DATA event terminates
    with a safe dependency error until AD/TIVIT validation is integrated,
    and receiving DTMF never marks a validated identity.
    """
    if isinstance(turn, IdentityDataTurn):
        raise IdentityValidationUnavailableError()
    engine: ConversationEngine | None = request.app.state.conversation_engine
    if engine is None:
        raise ConversationEngineUnavailableError()
    return await engine.handle_turn(
        ConversationTurn(
            conversation_id=conversation_id,
            transcript=turn.transcript,
            asr_confidence=turn.asr_confidence,
        )
    )


def create_app(engine: ConversationEngine | None = None) -> FastAPI:
    """Build the boundary.

    The Gemini-backed engine arrives with the next iteration; until then a
    transcript turn fails safely instead of faking a conversation.
    """
    app = FastAPI(title="CU013 Cally Square boundary", version="0.2.0")
    app.state.conversation_engine = engine
    app.include_router(router)
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
    return app
