"""Ephemeral turn state, the typed model decision and the LangGraph turn.

LangGraph orchestrates one technical turn in RAM: an optional model node
produces the typed conversational decision and the deterministic runtime
node keeps owning legality and durable state. Nothing here is durable and
no checkpointer is ever compiled.
"""

from enum import StrEnum
from functools import partial
from typing import Protocol, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, ConfigDict, Field

from app.session.record import Action, OperationStatus, PendingOperation, SessionRecord


class Route(StrEnum):
    """Route the turn decision carries for the Cally Square boundary."""

    CONTINUE = "CONTINUE"
    COLLECT_IDENTITY = "COLLECT_IDENTITY"
    COMPLETE = "COMPLETE"
    ESCALATE = "ESCALATE"


class ModelTurnDecision(BaseModel):
    """Typed structured model output for one turn. Transient; never durable."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    message: str = Field(min_length=1)
    route: Route
    action_requested: Action | None = None


class TurnModel(Protocol):
    """Minimal model capability the turn consumes; one call per normal turn.

    The model receives only the current transcript and the semantic
    projection of the durable record. Raw DTMF cannot reach this seam, the
    model never validates identity and never creates business results.
    """

    async def decide(
        self,
        *,
        transcript: str,
        identity_validated: bool,
        requested_action: Action | None,
        pending_operation: PendingOperation | None,
    ) -> ModelTurnDecision: ...


class TurnInput(BaseModel):
    """Per-turn transient input. Never persisted and never durable state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    transcript: str | None = None
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
    transcript: str | None
    model_decision: ModelTurnDecision | None


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
        transcript=turn.transcript,
        model_decision=None,
    )


async def run_model(state: GraphState, *, model: TurnModel) -> dict[str, ModelTurnDecision | None]:
    """Produce the typed decision from the transcript and semantic state.

    The model owns language and may suggest an action; it never validates
    identity, never creates business results and never executes side effects.
    """
    transcript = state["transcript"]
    if transcript is None:
        return {"model_decision": None}
    decision = await model.decide(
        transcript=transcript,
        identity_validated=state["identity_validated"],
        requested_action=state["requested_action"],
        pending_operation=state["pending_operation"],
    )
    return {"model_decision": decision}


def advance_turn(state: GraphState) -> TurnDelta:
    """Apply one deterministic turn with the runtime keeping the last word.

    A validated identity is durable and never downgraded. An action only
    becomes durable after a positive identity result. The model may suggest
    an action, but the runtime alone decides what becomes durable. While a
    durable operation is pending, another local request keeps the same
    operation identity instead of replacing it; this is durable local
    bookkeeping only and never executes, retries or deduplicates the
    external operation.
    """
    identity_validated = state["identity_validated"] or state["identity_ok"] is True
    requested_action = state["requested_action"]
    pending_operation = state["pending_operation"]

    action_requested = state["action_requested"]
    model_decision = state["model_decision"]
    if action_requested is None and model_decision is not None:
        action_requested = model_decision.action_requested

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


def build_turn_graph(model: TurnModel | None = None) -> TurnGraph:
    """Compile the turn graph without a persistent checkpointer.

    With a model the graph runs START -> run_model -> advance_turn -> END:
    exactly one model call per turn and the runtime node keeps the last
    word on legality and durable state. Without a model only the runtime
    node runs, which keeps the deterministic session core self-contained.
    """
    builder = StateGraph(GraphState)
    builder.add_node("advance_turn", advance_turn)
    if model is not None:
        builder.add_node("run_model", partial(run_model, model=model))
        builder.add_edge(START, "run_model")
        builder.add_edge("run_model", "advance_turn")
    else:
        builder.add_edge(START, "advance_turn")
    builder.add_edge("advance_turn", END)
    return builder.compile()
