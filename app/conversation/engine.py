"""Conversational seam and the real engine over the thin session turn."""

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.conversation.errors import InvalidModelOutputError
from app.session.outcome import NextStep
from app.session.service import TurnService
from app.session.turns import ExternalActionCommand, TurnInput

__all__ = [
    "ConversationEngine",
    "ConversationTurn",
    "SessionConversationEngine",
    "TurnOutcome",
]


class TurnOutcome(BaseModel):
    """Conversational result for one turn; the engine owns message and step.

    ``command`` travels only with ``EXECUTE_ACTION``: it is the runtime's
    authorized external order, never a model proposal.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    message: str
    next_step: NextStep
    command: ExternalActionCommand | None = None


class ConversationTurn(BaseModel):
    """Transient engine input; never durable, never raw DTMF.

    ``temporary_password`` is the ephemeral voice secret XCALLY re-sends on
    every presentation turn; it lives only in the current request and never
    reaches durable state.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    conversation_id: str = Field(min_length=1)
    transcript: str | None = None
    temporary_password: SecretStr | None = None
    asr_confidence: float | None = None


class ConversationEngine(Protocol):
    """Seam the conversational engine implements for the HTTP boundary."""

    async def handle_turn(self, turn: ConversationTurn) -> TurnOutcome: ...


class SessionConversationEngine:
    """Real engine: one thin-session turn that includes the model call.

    The runtime validates the transient model decision into the boundary
    outcome; the runtime keeps owning legality, durable state and the truth
    of business results, and the model never authorizes or executes anything.
    """

    def __init__(self, service: TurnService) -> None:
        self._service = service

    async def handle_turn(self, turn: ConversationTurn) -> TurnOutcome:
        result = await self._service.handle_turn(
            turn.conversation_id,
            TurnInput(
                transcript=turn.transcript,
                temporary_password=turn.temporary_password,
            ),
        )
        outcome = result.outcome
        if outcome is None:
            raise InvalidModelOutputError("turn completed without a model decision")
        return TurnOutcome(
            message=outcome.message, next_step=outcome.next_step, command=outcome.command
        )
