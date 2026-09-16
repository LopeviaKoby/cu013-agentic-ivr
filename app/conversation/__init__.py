"""Conversational seam for the XCALLY turn boundary.

Requests flow HTTP adapter -> ConversationEngine -> runtime services. The
engine contract is the only extension point for the Gemini iteration.
"""

from app.conversation.engine import (
    ConversationEngine,
    ConversationTurn,
    Route,
    TurnOutcome,
)

__all__ = [
    "ConversationEngine",
    "ConversationTurn",
    "Route",
    "TurnOutcome",
]
