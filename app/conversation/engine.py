"""Minimal conversational seam between the HTTP boundary and the engine.

No conversational logic lives here. The next iteration implements this
protocol with Gemini; that engine owns language, while the runtime keeps
owning legality, authorization, state and side effects.
"""

from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class Route(StrEnum):
    """Route Cally Square consumes from a turn response."""

    CONTINUE = "CONTINUE"
    COLLECT_IDENTITY = "COLLECT_IDENTITY"
    COMPLETE = "COMPLETE"
    ESCALATE = "ESCALATE"


class TurnOutcome(BaseModel):
    """Conversational result for one turn; the engine owns message and route."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    message: str
    route: Route


class ConversationTurn(BaseModel):
    """Transient engine input; never durable and never raw DTMF."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    conversation_id: str = Field(min_length=1)
    transcript: str = Field(min_length=1)
    asr_confidence: float | None = None


class ConversationEngine(Protocol):
    """Seam the Gemini-backed conversational engine implements next."""

    async def handle_turn(self, turn: ConversationTurn) -> TurnOutcome: ...
