"""Deterministic tests for the RESET assistance-mode contract (schema v6).

Covers the durable mode, the v5→v6 migration inference, the identity gate,
the same-turn autonomous confirmation and the mode-switch invalidation with
no model, network or credentials.
"""

from app.session.actions import Action
from app.session.outcome import NextStep
from app.session.record import (
    AssistanceMode,
    ConversationGoal,
    OperationStatus,
    session_record_from_document,
    session_record_to_document,
)
from app.session.turns import (
    ConfirmationObservation,
    GoalFocus,
    GoalIntent,
    GoalProposal,
    Route,
    advance_turn,
)
from tests.session.doubles import (
    NOW,
    make_challenge,
    make_decision,
    make_dispatch,
    make_goal,
    make_identity,
    make_operation,
    make_record,
    make_state,
)


def _v5_document(record) -> dict[str, object]:  # type: ignore[no-untyped-def]
    """Simulate a stored v5 document: no assistance_mode key in the goal."""
    document = session_record_to_document(record)
    document["schema_version"] = 5
    goal = document.get("goal")
    if isinstance(goal, dict):
        goal.pop("assistance_mode", None)
    return document


# --- migration v5 -> v6 -----------------------------------------------------


def test_v5_reset_with_autonomous_evidence_migrates_to_autonomous() -> None:
    record = make_record(
        goal=ConversationGoal(action=Action.RESET_PASSWORD, revision=1),
        identity=make_identity(NOW),
        dispatch=make_dispatch(Action.RESET_PASSWORD, revision=1, operation_id="operation-1"),
        external_operation=make_operation(
            Action.RESET_PASSWORD, OperationStatus.CONFIRMED, operation_id="operation-1"
        ),
    )
    migrated = session_record_from_document(_v5_document(record))
    assert migrated.schema_version == 6
    assert migrated.goal is not None
    assert migrated.goal.assistance_mode is AssistanceMode.AUTONOMOUS


def test_v5_reset_without_autonomous_evidence_migrates_to_undecided() -> None:
    record = make_record(
        goal=ConversationGoal(action=Action.RESET_PASSWORD, revision=1),
        identity=make_identity(NOW),
    )
    migrated = session_record_from_document(_v5_document(record))
    assert migrated.goal is not None
    assert migrated.goal.assistance_mode is AssistanceMode.UNDECIDED


def test_v5_unlock_keeps_no_assistance_mode() -> None:
    record = make_record(
        goal=ConversationGoal(action=Action.UNLOCK_ACCOUNT, revision=1),
        identity=make_identity(NOW),
    )
    migrated = session_record_from_document(_v5_document(record))
    assert migrated.goal is not None
    assert migrated.goal.assistance_mode is None


def test_v6_round_trip_preserves_the_assistance_mode() -> None:
    record = make_record(
        goal=make_goal(Action.RESET_PASSWORD, assistance_mode=AssistanceMode.GUIDED),
        identity=make_identity(NOW),
    )
    restored = session_record_from_document(session_record_to_document(record))
    assert restored == record


# --- identity gate ----------------------------------------------------------


def _progress_turn(mode: AssistanceMode | None):  # type: ignore[no-untyped-def]
    return advance_turn(
        make_state(
            goal=make_goal(Action.RESET_PASSWORD, assistance_mode=mode),
            identity=make_identity(),
            model_decision=make_decision(route=Route.CONTINUE, goal_focus=GoalFocus.PROGRESS),
        )
    )


def test_undecided_and_guided_resets_never_capture_identity() -> None:
    for mode in (AssistanceMode.UNDECIDED, AssistanceMode.GUIDED):
        delta = _progress_turn(mode)
        assert delta["identity"].validated_at is None
        assert delta["outcome"] is not None
        assert delta["outcome"].next_step is NextStep.LISTEN


def test_autonomous_reset_requires_identity() -> None:
    delta = _progress_turn(AssistanceMode.AUTONOMOUS)
    assert delta["outcome"] is not None
    assert delta["outcome"].next_step is NextStep.COLLECT_IDENTITY


def test_unlock_keeps_the_existing_identity_behavior() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(),
            model_decision=make_decision(route=Route.CONTINUE, goal_focus=GoalFocus.PROGRESS),
        )
    )
    assert delta["outcome"] is not None
    assert delta["outcome"].next_step is NextStep.COLLECT_IDENTITY


# --- same-turn autonomous confirmation --------------------------------------


def _same_turn(mode: AssistanceMode | None, *, confirmation_request: bool = True):  # type: ignore[no-untyped-def]
    return advance_turn(
        make_state(
            goal=None,
            identity=make_identity(NOW),
            model_decision=make_decision(
                route=Route.CONTINUE,
                goal=GoalProposal(intent=GoalIntent.REQUEST, action=Action.RESET_PASSWORD),
                goal_focus=GoalFocus.PROGRESS,
                assistance_mode=mode,
                confirmation_request=confirmation_request,
            ),
        )
    )


def test_same_turn_autonomous_goal_opens_the_reset_challenge() -> None:
    delta = _same_turn(AssistanceMode.AUTONOMOUS)
    assert delta["goal"] is not None
    assert delta["goal"].assistance_mode is AssistanceMode.AUTONOMOUS
    assert delta["confirmation"] is not None
    assert delta["confirmation"].action is Action.RESET_PASSWORD
    assert delta["dispatch"] is None
    assert delta["outcome"] is not None
    assert delta["outcome"].next_step is NextStep.LISTEN


def test_same_turn_guided_or_undecided_opens_no_challenge() -> None:
    for mode in (AssistanceMode.GUIDED, AssistanceMode.UNDECIDED, None):
        delta = _same_turn(mode)
        assert delta["confirmation"] is None
        assert delta["dispatch"] is None
        assert delta["outcome"] is not None
        assert delta["outcome"].next_step is NextStep.LISTEN


# --- mode switch and stale authorizations -----------------------------------


def test_switch_to_guided_invalidates_the_autonomous_challenge() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.RESET_PASSWORD, assistance_mode=AssistanceMode.AUTONOMOUS),
            identity=make_identity(NOW),
            confirmation=make_challenge(Action.RESET_PASSWORD),
            model_decision=make_decision(
                route=Route.CONTINUE,
                assistance_mode=AssistanceMode.GUIDED,
            ),
        )
    )
    assert delta["goal"] is not None
    assert delta["goal"].assistance_mode is AssistanceMode.GUIDED
    assert delta["confirmation"] is None
    assert delta["dispatch"] is None


def test_guided_reset_cannot_dispatch_even_with_an_affirmation() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.RESET_PASSWORD, assistance_mode=AssistanceMode.GUIDED),
            identity=make_identity(NOW),
            model_decision=make_decision(
                route=Route.CONTINUE,
                confirmation_observation=ConfirmationObservation.AFFIRMATIVE,
            ),
        )
    )
    assert delta["confirmation"] is None
    assert delta["dispatch"] is None
    assert delta["external_operation"] is None


def test_a_stale_unlock_confirmation_cannot_authorize_reset() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.RESET_PASSWORD, assistance_mode=AssistanceMode.AUTONOMOUS),
            identity=make_identity(NOW),
            confirmation=make_challenge(Action.UNLOCK_ACCOUNT),
            model_decision=make_decision(
                route=Route.CONTINUE,
                confirmation_observation=ConfirmationObservation.AFFIRMATIVE,
            ),
        )
    )
    # The stale UNLOCK challenge dies with the goal mismatch and never
    # authorizes; the runtime re-issues a fresh RESET challenge instead.
    assert delta["dispatch"] is None
    assert delta["external_operation"] is None
    assert delta["confirmation"] is not None
    assert delta["confirmation"].action is Action.RESET_PASSWORD
