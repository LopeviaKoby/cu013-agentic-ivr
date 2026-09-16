"""Thin session turn cycle: load, ephemeral graph, consolidate, save.

The durable record is persisted before control returns to the caller. A crash
before the save leaves the last durable state untouched; the next turn
restarts from it.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from app.session.record import SCHEMA_VERSION, SessionRecord
from app.session.repository import SessionRepository
from app.session.turns import GraphState, TurnGraph, TurnInput, initial_graph_state


def consolidate(
    previous: SessionRecord,
    state: Mapping[str, Any],
    *,
    now: datetime,
) -> SessionRecord:
    """Build the next durable record from the closed durable projection only.

    The SessionRecord constructor validates every value, so a malformed
    ephemeral state fails before anything is persisted.
    """
    return SessionRecord(
        schema_version=SCHEMA_VERSION,
        conversation_id=previous.conversation_id,
        turn_count=previous.turn_count + 1,
        revision=previous.revision + 1,
        identity_validated=state["identity_validated"],
        requested_action=state["requested_action"],
        pending_operation=state["pending_operation"],
        created_at=previous.created_at,
        updated_at=now,
    )


class TurnService:
    """Executes one turn with exactly one load and one save in the normal path."""

    def __init__(self, repository: SessionRepository, graph: TurnGraph) -> None:
        self._repository = repository
        self._graph = graph

    async def handle_turn(self, conversation_id: str, turn: TurnInput) -> SessionRecord:
        """Run one turn and return only after the consolidated save completes."""
        record = await self._repository.load(conversation_id)
        state: GraphState = initial_graph_state(record, turn)
        final_state = await self._graph.ainvoke(state)
        record = consolidate(record, final_state, now=datetime.now(UTC))
        await self._repository.save(record)
        return record
