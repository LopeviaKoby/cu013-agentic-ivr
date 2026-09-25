"""Ephemeral turn tests: deterministic node, model seam, no checkpointer."""

from app.session.outcome import NextStep
from app.session.record import Action
from app.session.turns import (
    ModelTurnDecision,
    Route,
    advance_turn,
    build_turn_graph,
    run_model,
)
from tests.session.doubles import (
    FakeTurnModel,
    make_decision,
    make_goal,
    make_identity,
    make_state,
)


def test_turn_graph_has_no_persistent_checkpointer() -> None:
    assert build_turn_graph().checkpointer is None


def test_model_graph_runs_the_model_node_before_the_runtime_node() -> None:
    graph = build_turn_graph(model=FakeTurnModel())
    assert graph.checkpointer is None
    assert set(graph.get_graph().nodes) == {"__start__", "run_model", "advance_turn", "__end__"}


async def test_run_model_calls_the_model_once_with_transcript_and_projection() -> None:
    model = FakeTurnModel()
    update = await run_model(make_state(transcript="synthetic transcript 0000"), model=model)
    assert update == {"model_decision": model.decision, "memory_render_ms": None}
    assert len(model.calls) == 1
    assert model.calls[0]["transcript"] == "synthetic transcript 0000"
    assert model.calls[0]["identity_validated"] is False
    assert model.calls[0]["goal"] is None
    assert model.calls[0]["confirmation"] is None
    assert model.calls[0]["external_operation"] is None
    # With no recent memory no experimental block is rendered into the input.
    assert model.calls[0]["memory_context"] is None


async def test_run_model_projects_goal_and_identity_validity_only() -> None:
    model = FakeTurnModel()
    await run_model(
        make_state(
            transcript="synthetic transcript 0000",
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(),
        ),
        model=model,
    )
    assert model.calls[0]["identity_validated"] is False
    assert model.calls[0]["goal"] == make_goal(Action.UNLOCK_ACCOUNT)


async def test_run_model_without_transcript_does_not_call_the_model() -> None:
    model = FakeTurnModel()
    update = await run_model(make_state(), model=model)
    assert update == {"model_decision": None}
    assert model.calls == []


async def test_graph_returns_the_ephemeral_state_in_memory() -> None:
    graph = build_turn_graph()
    final = await graph.ainvoke(make_state())
    assert final["goal"] is None
    assert final["dispatch"] is None
    assert final["outcome"] is None


def test_model_contract_cannot_express_runtime_authority() -> None:
    """Identity, dispatch, external truth and delivery are not model fields.

    The experimental ``procedure_observation`` is a proposal cue only: the
    runtime validates it against the accepted guided slice and it never
    authorizes, dispatches or creates business truth.
    """
    assert set(ModelTurnDecision.model_fields) == {
        "message",
        "route",
        "goal",
        "confirmation_request",
        "confirmation_observation",
        "procedure_observation",
        "handoff_cause",
        "claims",
    }


async def test_safe_fallback_never_needs_a_second_model_call() -> None:
    model = FakeTurnModel()
    model.decision = make_decision(
        message="synthetic claim of business success",
        route=Route.COMPLETE,
        claims=[{"kind": "OPERATION_SUCCEEDED"}],
    )
    graph = build_turn_graph(model=model)
    final = await graph.ainvoke(make_state(transcript="synthetic transcript 0000"))
    assert len(model.calls) == 1
    outcome = final["outcome"]
    assert outcome is not None
    assert outcome.next_step is NextStep.LISTEN
    assert outcome.violations


async def test_model_suggestion_without_validated_identity_is_not_dispatchable() -> None:
    model = FakeTurnModel()
    model.decision = make_decision(
        route=Route.COLLECT_IDENTITY,
        goal={"intent": "REQUEST", "action": "UNLOCK_ACCOUNT"},
    )
    graph = build_turn_graph(model=model)
    final = await graph.ainvoke(make_state(transcript="synthetic transcript 0000"))
    assert final["goal"] is not None
    assert final["dispatch"] is None
    assert final["external_operation"] is None


def test_model_cannot_create_an_operation_without_a_boundary_event() -> None:
    opened = advance_turn(
        make_state(goal=make_goal(Action.RESET_PASSWORD), identity=make_identity())
    )
    assert opened["external_operation"] is None
    claimed = advance_turn(
        make_state(
            goal=make_goal(Action.RESET_PASSWORD),
            identity=make_identity(),
            model_decision=make_decision(
                route=Route.COMPLETE, claims=[{"kind": "OPERATION_SUCCEEDED"}]
            ),
        )
    )
    assert claimed["external_operation"] is None
    assert claimed["outcome"] is not None
    assert claimed["outcome"].next_step is NextStep.LISTEN


async def test_run_model_seam_passes_the_durable_procedure_step() -> None:
    """The model seam receives the durable step for deterministic projection."""
    from app.session.memory import GUIDED_PROCEDURE_ID, ExperimentalProcedureState

    model = FakeTurnModel()
    procedure = ExperimentalProcedureState(
        procedure_id=GUIDED_PROCEDURE_ID,
        current_step="microsoft_portal",
        goal_revision=1,
        opened_at=make_state()["now"],
    )
    await run_model(
        make_state(
            goal=make_goal(Action.RESET_PASSWORD, revision=1),
            transcript="hola",
            experimental_procedure=procedure,
        ),
        model=model,
    )
    assert model.calls[0]["procedure_current"] == "microsoft_portal"
    projection = model.calls[0]["state_projection"]
    assert projection.active_goal == "RESET_PASSWORD"
    assert projection.procedure_current == "microsoft_portal"


async def test_run_model_seam_without_procedure_passes_none() -> None:
    model = FakeTurnModel()
    await run_model(make_state(transcript="hola"), model=model)
    assert model.calls[0]["procedure_current"] is None
