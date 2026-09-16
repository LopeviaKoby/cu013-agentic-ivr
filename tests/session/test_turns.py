"""Ephemeral turn tests: deterministic node, model seam, no checkpointer."""

from app.session.record import Action, OperationStatus
from app.session.turns import (
    GraphState,
    ModelTurnDecision,
    Route,
    advance_turn,
    build_turn_graph,
    run_model,
)
from tests.session.doubles import FakeTurnModel


def make_state(**overrides: object) -> GraphState:
    state: dict[str, object] = {
        "conversation_id": "conversation-1",
        "identity_validated": False,
        "requested_action": None,
        "pending_operation": None,
        "identity_ok": None,
        "action_requested": None,
        "operation_result": None,
        "transcript": None,
        "model_decision": None,
    }
    state.update(overrides)
    return GraphState(**state)


def test_turn_graph_has_no_persistent_checkpointer() -> None:
    assert build_turn_graph().checkpointer is None


def test_action_before_positive_identity_is_not_durable() -> None:
    delta = advance_turn(make_state(action_requested=Action.RESET_PASSWORD))
    assert delta["identity_validated"] is False
    assert delta["requested_action"] is None
    assert delta["pending_operation"] is None


def test_failed_identity_attempt_never_downgrades_validated_identity() -> None:
    delta = advance_turn(make_state(identity_validated=True, identity_ok=False))
    assert delta["identity_validated"] is True


def test_positive_identity_then_action_creates_a_pending_operation() -> None:
    delta = advance_turn(make_state(identity_ok=True, action_requested=Action.UNLOCK_ACCOUNT))
    assert delta["identity_validated"] is True
    assert delta["requested_action"] is Action.UNLOCK_ACCOUNT
    assert delta["pending_operation"] is not None
    assert delta["pending_operation"].action is Action.UNLOCK_ACCOUNT
    assert delta["pending_operation"].status is OperationStatus.PENDING
    assert delta["pending_operation"].operation_id


def test_duplicate_request_does_not_replace_the_open_operation() -> None:
    first = advance_turn(
        make_state(identity_validated=True, action_requested=Action.RESET_PASSWORD)
    )
    assert first["pending_operation"] is not None
    second = advance_turn(
        make_state(
            identity_validated=True,
            action_requested=Action.RESET_PASSWORD,
            pending_operation=first["pending_operation"],
        )
    )
    assert second["pending_operation"] is first["pending_operation"]


def test_terminal_result_resolves_the_open_operation() -> None:
    opened = advance_turn(
        make_state(identity_validated=True, action_requested=Action.RESET_PASSWORD)
    )
    assert opened["pending_operation"] is not None
    resolved = advance_turn(
        make_state(
            identity_validated=True,
            pending_operation=opened["pending_operation"],
            operation_result=OperationStatus.CONFIRMED,
        )
    )
    assert resolved["pending_operation"] is not None
    assert resolved["pending_operation"].operation_id == opened["pending_operation"].operation_id
    assert resolved["pending_operation"].status is OperationStatus.CONFIRMED


def test_pending_result_does_not_resolve_an_open_operation() -> None:
    opened = advance_turn(
        make_state(identity_validated=True, action_requested=Action.RESET_PASSWORD)
    )
    unchanged = advance_turn(
        make_state(
            identity_validated=True,
            pending_operation=opened["pending_operation"],
            operation_result=OperationStatus.PENDING,
        )
    )
    assert unchanged["pending_operation"] is opened["pending_operation"]


async def test_graph_returns_the_ephemeral_state_in_memory() -> None:
    graph = build_turn_graph()
    final = await graph.ainvoke(
        make_state(identity_ok=True, action_requested=Action.UNLOCK_ACCOUNT)
    )
    assert final["identity_ok"] is True
    assert final["action_requested"] is Action.UNLOCK_ACCOUNT
    assert final["operation_result"] is None
    assert final["identity_validated"] is True
    assert final["pending_operation"] is not None


def test_model_graph_runs_the_model_node_before_the_runtime_node() -> None:
    graph = build_turn_graph(model=FakeTurnModel())
    assert graph.checkpointer is None
    assert set(graph.get_graph().nodes) == {"__start__", "run_model", "advance_turn", "__end__"}


async def test_run_model_calls_the_model_once_with_transcript_and_projection() -> None:
    model = FakeTurnModel()
    update = await run_model(make_state(transcript="synthetic transcript 0000"), model=model)
    assert update == {"model_decision": model.decision}
    assert len(model.calls) == 1
    assert model.calls[0]["transcript"] == "synthetic transcript 0000"
    assert model.calls[0]["identity_validated"] is False


async def test_run_model_without_transcript_does_not_call_the_model() -> None:
    model = FakeTurnModel()
    update = await run_model(make_state(), model=model)
    assert update == {"model_decision": None}
    assert model.calls == []


def test_model_suggestion_without_validated_identity_is_not_durable() -> None:
    decision = ModelTurnDecision(
        message="synthetic message",
        route=Route.COLLECT_IDENTITY,
        action_requested=Action.UNLOCK_ACCOUNT,
    )
    delta = advance_turn(make_state(identity_validated=False, model_decision=decision))
    assert delta["identity_validated"] is False
    assert delta["requested_action"] is None
    assert delta["pending_operation"] is None


def test_model_suggestion_with_validated_identity_becomes_a_pending_operation() -> None:
    decision = ModelTurnDecision(
        message="synthetic message",
        route=Route.CONTINUE,
        action_requested=Action.RESET_PASSWORD,
    )
    delta = advance_turn(make_state(identity_validated=True, model_decision=decision))
    assert delta["requested_action"] is Action.RESET_PASSWORD
    assert delta["pending_operation"] is not None
    assert delta["pending_operation"].status is OperationStatus.PENDING


def test_model_cannot_resolve_operations_without_a_runtime_result() -> None:
    opened = advance_turn(
        make_state(
            identity_validated=True,
            model_decision=ModelTurnDecision(
                message="synthetic message",
                route=Route.CONTINUE,
                action_requested=Action.RESET_PASSWORD,
            ),
        )
    )
    claimed = advance_turn(
        make_state(
            identity_validated=True,
            pending_operation=opened["pending_operation"],
            model_decision=ModelTurnDecision(
                message="synthetic claim of success", route=Route.COMPLETE
            ),
        )
    )
    assert claimed["pending_operation"] is not None
    assert claimed["pending_operation"].status is OperationStatus.PENDING
