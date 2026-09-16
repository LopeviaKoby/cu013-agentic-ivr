"""Ephemeral turn tests: deterministic node, transient state, no checkpointer."""

from app.session.record import Action, OperationStatus
from app.session.turns import GraphState, advance_turn, build_turn_graph


def make_state(**overrides: object) -> GraphState:
    state: dict[str, object] = {
        "conversation_id": "conversation-1",
        "identity_validated": False,
        "requested_action": None,
        "pending_operation": None,
        "identity_ok": None,
        "action_requested": None,
        "operation_result": None,
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
