"""Deterministic regressions from E2E call Ivr02-1790566892.6105.

Covers the confirmation lost after VOICE_INPUT_FAILURE, the historical
operation projection while a different goal is active, and the closing
message/next_step coherence. No model, network or credentials.
"""

from app.session.actions import Action
from app.session.outcome import NextStep
from app.session.record import AssistanceMode, OperationStatus
from app.session.state_projection import project_model_state
from app.session.turns import (
    COMPLETE_FAREWELL_MESSAGE,
    SAFE_FALLBACK_MESSAGE,
    ConfirmationEvent,
    ConfirmationObservation,
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
    make_state,
)


def test_affirmation_without_a_live_challenge_reissues_the_confirmation() -> None:
    """After a voice failure invalidated the challenge, an affirmation must
    not become an execution announcement: the runtime re-establishes the
    specific confirmation, asks again and never dispatches."""
    state = make_state(
        goal=make_goal(Action.UNLOCK_ACCOUNT),
        identity=make_identity(NOW),
        confirmation=None,
        model_decision=make_decision(
            route=Route.CONTINUE,
            message="Perfecto, procedemos con el desbloqueo.",
            confirmation_observation=ConfirmationObservation.AFFIRMATIVE,
        ),
    )
    delta = advance_turn(state)
    outcome = delta["outcome"]
    assert outcome is not None
    assert delta["dispatch"] is None
    assert delta["external_operation"] is None
    assert outcome.next_step is NextStep.LISTEN
    assert outcome.message != "Perfecto, procedemos con el desbloqueo."
    assert delta["confirmation"] is not None
    assert delta["confirmation"].action is Action.UNLOCK_ACCOUNT


def test_affirmation_without_identity_falls_back_safely() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(),
            confirmation=None,
            model_decision=make_decision(
                route=Route.CONTINUE,
                message="Perfecto, procedemos con el desbloqueo.",
                confirmation_observation=ConfirmationObservation.AFFIRMATIVE,
            ),
        )
    )
    outcome = delta["outcome"]
    assert outcome is not None
    assert delta["confirmation"] is None
    assert delta["dispatch"] is None
    assert outcome.message == SAFE_FALLBACK_MESSAGE
    assert outcome.violations


def test_voice_failure_invalidates_the_challenge_and_a_fresh_one_recovers() -> None:
    """A failed capture clears the challenge; a later explicit request opens a
    fresh challenge and only its affirmative authorizes the dispatch."""
    invalidated = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(NOW),
            confirmation=make_challenge(Action.UNLOCK_ACCOUNT),
            confirmation_event=ConfirmationEvent.ASR_TIMEOUT,
            model_decision=make_decision(route=Route.CONTINUE),
        )
    )
    assert invalidated["confirmation"] is None
    assert invalidated["dispatch"] is None

    recovered = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(NOW),
            confirmation=None,
            model_decision=make_decision(
                route=Route.CONTINUE,
                confirmation_request=True,
            ),
        )
    )
    assert recovered["confirmation"] is not None
    assert recovered["dispatch"] is None

    authorized = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(NOW),
            confirmation=make_challenge(Action.UNLOCK_ACCOUNT),
            model_decision=make_decision(
                route=Route.CONTINUE,
                confirmation_observation=ConfirmationObservation.AFFIRMATIVE,
            ),
        )
    )
    assert authorized["dispatch"] is not None
    assert authorized["external_operation"] is not None


def test_projection_names_the_action_of_the_historical_result() -> None:
    """The historical UNLOCK result stays visible but labelled with its own
    action so it is never read as the state of the active RESET goal."""
    projection = project_model_state(
        goal=make_goal(Action.RESET_PASSWORD, assistance_mode=AssistanceMode.AUTONOMOUS),
        identity=make_identity(NOW),
        confirmation=None,
        dispatch=make_dispatch(Action.UNLOCK_ACCOUNT, revision=1, operation_id="operation-1"),
        operation=make_operation(
            Action.UNLOCK_ACCOUNT, OperationStatus.CONFIRMED, operation_id="operation-1"
        ),
        presentation=None,
        procedure=None,
        now=NOW,
    )
    assert projection.active_goal == "RESET_PASSWORD"
    assert projection.external_operation_status == "confirmed"
    assert projection.external_operation_action == "UNLOCK_ACCOUNT"


def test_complete_closes_with_a_farewell_not_an_open_question() -> None:
    delta = advance_turn(
        make_state(
            model_decision=make_decision(
                route=Route.COMPLETE,
                message="De acuerdo. \u00bfHay algo m\u00e1s en lo que pueda ayudarte?",
            )
        )
    )
    outcome = delta["outcome"]
    assert outcome is not None
    assert outcome.next_step is NextStep.COMPLETE
    assert outcome.message == COMPLETE_FAREWELL_MESSAGE
    assert "?" not in outcome.message
