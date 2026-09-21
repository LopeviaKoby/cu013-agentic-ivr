"""Typed external HTTP contract consumed by Cally Square.

This module defines the only request and response shapes the boundary
accepts and emits:

- ``/turns`` carries one ASR transcript and returns the conversational
  message, the closed route and, only when the runtime created a durable
  dispatch guard, the external action command XCALLY must execute;
- ``/integration-events`` carries one PII-safe technical event and returns a
  flat acknowledgment plus a directive.

Raw DTMF, document, birth date, password and email are not part of either
contract and are rejected by the closed request models.
"""

from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.session.integration import (
    IntegrationDirective,
    IntegrationEvent,
    IntegrationOperationState,
)
from app.session.turns import BoundaryRoute, ExternalActionCommand


class TranscriptTurn(BaseModel):
    """ASR transcript turn; only the transcript itself is required."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    transcript: str = Field(min_length=1)
    asr_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    channel: Literal["voice"] = "voice"


class TurnResponse(BaseModel):
    """Fields Cally Square consumes plus the internal turn correlation id.

    ``command`` is non-null if and only if ``route`` is ``EXECUTE_ACTION``;
    the runtime creates it only after the durable dispatch guard is persisted.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    message: str
    route: BoundaryRoute
    turn_id: str = Field(min_length=1)
    command: ExternalActionCommand | None = None

    @model_validator(mode="after")
    def _command_only_with_execute_action(self) -> Self:
        if self.command is not None and self.route is not BoundaryRoute.EXECUTE_ACTION:
            raise ValueError("command is only valid with EXECUTE_ACTION")
        if self.route is BoundaryRoute.EXECUTE_ACTION and self.command is None:
            raise ValueError("EXECUTE_ACTION requires a command")
        return self


class IntegrationEventResponse(BaseModel):
    """Flat response for Cally Square: ack, state, directive and TTS message.

    ``message`` is null when no TTS should be spoken; ``directive`` is never
    the conversational route enum. ``operation_state`` is null when the event
    did not involve an external operation.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    acknowledged: bool
    operation_state: IntegrationOperationState | None = None
    directive: IntegrationDirective
    message: str | None = None


class ErrorCode(StrEnum):
    """Stable boundary error taxonomy."""

    VALIDATION = "validation"
    AUTHORIZATION = "authorization"
    CONFLICT_OR_DUPLICATE = "conflict_or_duplicate"
    DEPENDENCY_TIMEOUT = "dependency_timeout"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    INTERNAL = "internal"


class ErrorBody(BaseModel):
    """Safe error payload: a code and a static message, never request data."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: ErrorCode
    message: str


class ErrorResponse(BaseModel):
    """Boundary error envelope; the final XCALLY error shape is still open."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    error: ErrorBody


__all__ = [
    "ErrorBody",
    "ErrorCode",
    "ErrorResponse",
    "IntegrationEvent",
    "IntegrationEventResponse",
    "TranscriptTurn",
    "TurnResponse",
]
