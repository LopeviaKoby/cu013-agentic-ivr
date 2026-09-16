"""Ephemeral turn state and the minimal deterministic LangGraph turn.

LangGraph orchestrates one technical turn in RAM. It is compiled without a
checkpointer: nothing here is durable, and the graph holds no external
capabilities.
"""

from typing import TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, ConfigDict

from app.session.record import Action, OperationStatus, PendingOperation, SessionRecord


class TurnInput(BaseModel):
    """Per-turn transient input. Never persisted and never durable state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    identity_ok: bool | None = None
    action_requested: Action | None = None
    operation_result: OperationStatus | None = None


class GraphState(TypedDict):
    """Ephemeral state: durable projection plus per-turn transient input."""

    conversation_id: str
    identity_validated: bool
    requested_action: Action | None
    pending_operation: PendingOperation | None
    identity_ok: bool | None
    action_requested: Action | None
    operation_result: OperationStatus | None


class TurnDelta(TypedDict):
    """The durable projection one turn may change."""

    identity_validated: bool
    requested_action: Action | None
    pending_operation: PendingOperation | None


def initial_graph_state(record: SessionRecord, turn: TurnInput) -> GraphState:
    """Build the ephemeral state from durable state plus this turn's input."""
    return GraphState(
        conversation_id=record.conversation_id,
        identity_validated=record.identity_validated,
        requested_action=record.requested_action,
        pending_operation=record.pending_operation,
        identity_ok=turn.identity_ok,
        action_requested=turn.action_requested,
        operation_result=turn.operation_result,
    )


def advance_turn(state: GraphState) -> TurnDelta:
    """Apply one deterministic turn without external capabilities.

    A validated identity is durable and never downgraded. An action only
    becomes durable after a positive identity result. While a durable
    operation is pending, another local request keeps the same operation
    identity instead of replacing it; this is durable local bookkeeping only
    and never executes, retries or deduplicates the external operation.
    """
    identity_validated = state["identity_validated"] or state["identity_ok"] is True
    requested_action = state["requested_action"]
    pending_operation = state["pending_operation"]

    action_requested = state["action_requested"]
    operation_is_open = (
        pending_operation is not None and pending_operation.status is OperationStatus.PENDING
    )
    if action_requested is not None and identity_validated and not operation_is_open:
        requested_action = action_requested
        pending_operation = PendingOperation(
            operation_id=uuid4().hex,
            action=action_requested,
        )

    operation_result = state["operation_result"]
    if (
        operation_result is not None
        and operation_result is not OperationStatus.PENDING
        and pending_operation is not None
        and pending_operation.status is OperationStatus.PENDING
    ):
        pending_operation = PendingOperation(
            operation_id=pending_operation.operation_id,
            action=pending_operation.action,
            status=operation_result,
        )

    return TurnDelta(
        identity_validated=identity_validated,
        requested_action=requested_action,
        pending_operation=pending_operation,
    )


TurnGraph = CompiledStateGraph[GraphState, None, GraphState, GraphState]


def build_turn_graph() -> TurnGraph:
    """Compile the single-node turn graph without a persistent checkpointer."""
    builder = StateGraph(GraphState)
    builder.add_node("advance_turn", advance_turn)
    builder.add_edge(START, "advance_turn")
    builder.add_edge("advance_turn", END)
    return builder.compile()
