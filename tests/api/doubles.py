"""Deterministic doubles and synthetic fixtures for the boundary tests.

No model, network, Firestore or credentials are involved. Every value is
synthetic and PII-safe.
"""

from app.conversation.engine import ConversationTurn, Route, TurnOutcome
from app.session.service import TurnService
from app.session.turns import TurnInput

SYNTHETIC_API_KEY = "synthetic-api-key-0000"
SYNTHETIC_TRANSCRIPT = "synthetic transcript 0000"
SYNTHETIC_DTMF = "SYNTHETIC-DTMF-0000"

TURNS_URL = "/api/v1/conversations/{conversation_id}/turns"


def turns_url(conversation_id: str) -> str:
    return TURNS_URL.format(conversation_id=conversation_id)


class RecordingConversationEngine:
    """Engine double implementing the ConversationEngine seam.

    It can delegate the durable turn to the real TurnService so tests prove
    that the path conversation_id reaches the session repository.
    """

    def __init__(self, service: TurnService | None = None) -> None:
        self._service = service
        self.turns: list[ConversationTurn] = []
        self.outcome = TurnOutcome(message="synthetic message", route=Route.CONTINUE)
        self.error: Exception | None = None

    async def handle_turn(self, turn: ConversationTurn) -> TurnOutcome:
        self.turns.append(turn)
        if self.error is not None:
            raise self.error
        if self._service is not None:
            await self._service.handle_turn(turn.conversation_id, TurnInput())
        return self.outcome
