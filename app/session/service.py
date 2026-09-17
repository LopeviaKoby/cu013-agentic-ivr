"""Thin session turn cycle: load, ephemeral graph, consolidate, save.

The durable record is persisted before control returns to the caller. A crash
before the save leaves the last durable state untouched; the next turn
restarts from it. Segment timing goes through the optional metrics seam with
fixed PII-safe names only.
"""

import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, cast

from pydantic import BaseModel, ConfigDict

from app.session.metrics import NullTurnMetrics, TurnMetrics
from app.session.record import SessionRecord
from app.session.repository import SessionRepository
from app.session.turns import (
    GraphState,
    ModelTurnDecision,
    TurnGraph,
    TurnInput,
    TurnOutcomeState,
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
        conversation_id=previous.conversation_id,
        turn_count=previous.turn_count + 1,
        revision=previous.revision + 1,
        goal=state["goal"],
        identity=state["identity"],
        confirmation=state["confirmation"],
        dispatch=state["dispatch"],
        external_operation=state["external_operation"],
        created_at=previous.created_at,
        updated_at=now,
    )


class TurnResult(BaseModel):
    """One completed turn: durable record plus transient model output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record: SessionRecord
    decision: ModelTurnDecision | None
    outcome: TurnOutcomeState | None


class TurnService:
    """Executes one turn with exactly one load and one save in the normal path."""

    def __init__(
        self,
        repository: SessionRepository,
        graph: TurnGraph,
        metrics: TurnMetrics | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._graph = graph
        self._metrics: TurnMetrics = metrics or NullTurnMetrics()
        self._clock: Callable[[], datetime] = clock or (lambda: datetime.now(UTC))

    async def handle_turn(self, conversation_id: str, turn: TurnInput) -> TurnResult:
        """Run one turn and return only after the consolidated save completes."""
        now = self._clock()
        record = await self._load(conversation_id, now=now)
        state: GraphState = initial_graph_state(record, turn, now=now)
        final_state = await self._invoke_graph(state)
        record = consolidate(record, final_state, now=now)
        await self._save(record)
        return TurnResult(
            record=record,
            decision=final_state["model_decision"],
            outcome=final_state["outcome"],
        )

    async def _load(self, conversation_id: str, *, now: datetime) -> SessionRecord:
        start = time.monotonic()
        try:
            return await self._repository.load(conversation_id, now=now)
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
