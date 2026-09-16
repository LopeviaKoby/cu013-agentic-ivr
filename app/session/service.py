"""Thin session turn cycle: load, ephemeral graph, consolidate, save.

The durable record is persisted before control returns to the caller. A crash
before the save leaves the last durable state untouched; the next turn
restarts from it. Segment timing goes through the optional metrics seam with
fixed PII-safe names only.
"""

import time
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast

from pydantic import BaseModel, ConfigDict

from app.session.metrics import NullTurnMetrics, TurnMetrics
from app.session.record import SCHEMA_VERSION, SessionRecord
from app.session.repository import SessionRepository
from app.session.turns import (
    GraphState,
    ModelTurnDecision,
    TurnGraph,
    TurnInput,
    initial_graph_state,
)


def consolidate(
    previous: SessionRecord,
    state: Mapping[str, Any],
    *,
    now: datetime,
) -> SessionRecord:
    """Build the next durable record from the closed durable projection only.

    The SessionRecord constructor validates every value, so a malformed
    ephemeral state fails before anything is persisted. Transcripts and model
    decisions never enter this projection.
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


class TurnResult(BaseModel):
    """One completed turn: durable record plus the transient model decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record: SessionRecord
    decision: ModelTurnDecision | None


class TurnService:
    """Executes one turn with exactly one load and one save in the normal path."""

    def __init__(
        self,
        repository: SessionRepository,
        graph: TurnGraph,
        metrics: TurnMetrics | None = None,
    ) -> None:
        self._repository = repository
        self._graph = graph
        self._metrics: TurnMetrics = metrics or NullTurnMetrics()

    async def handle_turn(self, conversation_id: str, turn: TurnInput) -> TurnResult:
        """Run one turn and return only after the consolidated save completes."""
        record = await self._load(conversation_id)
        state: GraphState = initial_graph_state(record, turn)
        final_state = await self._invoke_graph(state)
        record = consolidate(record, final_state, now=datetime.now(UTC))
        await self._save(record)
        return TurnResult(record=record, decision=final_state["model_decision"])

    async def _load(self, conversation_id: str) -> SessionRecord:
        start = time.monotonic()
        try:
            return await self._repository.load(conversation_id)
        finally:
            self._metrics.record_segment("session_load", _elapsed_ms(start))

    async def _invoke_graph(self, state: GraphState) -> GraphState:
        start = time.monotonic()
        try:
            return cast(GraphState, await self._graph.ainvoke(state))
        finally:
            self._metrics.record_segment("graph", _elapsed_ms(start))

    async def _save(self, record: SessionRecord) -> None:
        start = time.monotonic()
        try:
            await self._repository.save(record)
        finally:
            self._metrics.record_segment("session_save", _elapsed_ms(start))


def _elapsed_ms(start: float) -> float:
    return (time.monotonic() - start) * 1000.0
