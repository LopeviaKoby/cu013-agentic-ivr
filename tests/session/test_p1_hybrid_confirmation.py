"""Deterministic behavior table for P1 hybrid confirmation.

Owner-closed rules: the LLM interprets language and may render a
re-confirmation; the runtime alone opens/invalidates/consumes challenges,
decides next_step, and authorizes dispatch. No model, network, or
credentials are involved.
"""

from app.session.actions import Action
from app.session.outcome import NextStep
from app.session.record import AssistanceMode, OperationStatus
from app.session.semantic_obligation import (
    ExpectedUserResponse,
    SemanticObligationProjection,
    derive_semantic_obligation,
    render_semantic_obligation,
)
from app.session.turns import (
    SAFE_FALLBACK_MESSAGE,
    ConfirmationEvent,
    ConfirmationObservation,
    GoalFocus,
    GoalIntent,
    GoalProposal,
    Route,
    _reconfirmation_message,
    advance_turn,
)
from tests.session.doubles import (
    NOW,
    make_challenge,
    make_decision,
    make_goal,
    make_identity,
    make_state,
)

RESET_CANONICAL = _reconfirmation_message(Action.RESET_PASSWORD)
UNLOCK_CANONICAL = _reconfirmation_message(Action.UNLOCK_ACCOUNT)


# --- first deterministic confirmation ----------------------------------------


def test_valid_identity_plus_unlock_opens_deterministic_first_confirmation() -> None:
    from app.session.turns import IdentityOutcome

    delta = advance_turn(
        make_state(
            identity=make_identity(),
            identity_outcome=IdentityOutcome.VALIDATED,
            model_decision=make_decision(
                route=Route.CONTINUE,
                goal=GoalProposal(intent=GoalIntent.REQUEST, action=Action.UNLOCK_ACCOUNT),
                confirmation_request=True,
            ),
        )
    )
    outcome = delta["outcome"]
    assert outcome is not None
    assert delta["identity"].validated_at == NOW
    assert delta["goal"] is not None
    assert delta["goal"].action is Action.UNLOCK_ACCOUNT
    assert outcome.next_step is NextStep.LISTEN
    assert outcome.violations == ()
    assert outcome.message == UNLOCK_CANONICAL
    assert delta["confirmation"] is not None
    assert delta["confirmation"].action is Action.UNLOCK_ACCOUNT
    assert delta["confirmation"].identity_validated_at == NOW
    assert delta["dispatch"] is None


def test_undecided_to_autonomous_choice_speaks_canonical_first() -> None:
    from app.session.record import AssistanceMode as Mode

    delta = advance_turn(
        make_state(
            goal=make_goal(Action.RESET_PASSWORD, assistance_mode=Mode.UNDECIDED),
            identity=make_identity(NOW),
            model_decision=make_decision(
                route=Route.CONTINUE,
                assistance_mode=Mode.AUTONOMOUS,
                confirmation_request=True,
            ),
        )
    )
    outcome = delta["outcome"]
    assert outcome is not None
    assert delta["goal"] is not None
    assert delta["goal"].assistance_mode is Mode.AUTONOMOUS
    assert outcome.message == RESET_CANONICAL
    assert outcome.next_step is NextStep.LISTEN
    assert outcome.violations == ()
    assert delta["confirmation"] is not None
    assert delta["dispatch"] is None


def test_reset_autonomous_with_valid_identity_opens_deterministic_first() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.RESET_PASSWORD, assistance_mode=AssistanceMode.AUTONOMOUS),
            identity=make_identity(NOW),
            model_decision=make_decision(
                route=Route.CONTINUE,
                message="Allow me to handle it, confirming now?",
                confirmation_request=True,
            ),
        )
    )
    outcome = delta["outcome"]
    assert outcome is not None
    # The model draft is replaced: first entry speaks the canonical message.
    assert outcome.message == RESET_CANONICAL
    assert outcome.message != "Allow me to handle it, confirming now?"
    assert outcome.next_step is NextStep.LISTEN
    assert outcome.violations == ()
    assert delta["confirmation"] is not None
    assert delta["confirmation"].action is Action.RESET_PASSWORD
    assert delta["dispatch"] is None


# --- side question during confirmation ----------------------------------------


def _live_reset_challenge():  # type: ignore[no-untyped-def]
    return make_state(
        goal=make_goal(Action.RESET_PASSWORD, assistance_mode=AssistanceMode.AUTONOMOUS),
        identity=make_identity(NOW),
        confirmation=make_challenge(Action.RESET_PASSWORD, challenge_id="challenge-a"),
        model_decision=make_decision(
            route=Route.CONTINUE,
            message="It is usually quick. Shall I continue with the reset?",
            confirmation_request=True,
        ),
    )


def test_side_question_with_rerequest_rotates_to_a_new_model_rendered_challenge() -> None:
    delta = advance_turn(_live_reset_challenge())
    outcome = delta["outcome"]
    assert outcome is not None
    assert delta["dispatch"] is None
    assert outcome.next_step is NextStep.LISTEN
    assert outcome.violations == ()
    # The old challenge expired; the fresh one is bound identically but new.
    assert delta["confirmation"] is not None
    assert delta["confirmation"].challenge_id != "challenge-a"
    assert delta["confirmation"].action is Action.RESET_PASSWORD
    assert delta["confirmation"].goal_revision == 1
    assert delta["confirmation"].identity_validated_at == NOW
    # The candidate message is preserved, not substituted.
    assert outcome.message == "It is usually quick. Shall I continue with the reset?"


def test_side_question_without_rerequest_expires_without_replacement() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.RESET_PASSWORD, assistance_mode=AssistanceMode.AUTONOMOUS),
            identity=make_identity(NOW),
            confirmation=make_challenge(Action.RESET_PASSWORD, challenge_id="challenge-a"),
            model_decision=make_decision(route=Route.CONTINUE),
        )
    )
    outcome = delta["outcome"]
    assert outcome is not None
    assert outcome.next_step is NextStep.LISTEN
    assert outcome.violations == ()
    assert delta["confirmation"] is None
    assert delta["dispatch"] is None
    assert delta["goal"] is not None


# --- affirmative / negative / ambiguous ----------------------------------------


def test_affirmative_consumes_and_dispatches_exactly_once() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(NOW),
            confirmation=make_challenge(Action.UNLOCK_ACCOUNT, challenge_id="challenge-b"),
            model_decision=make_decision(
                confirmation_observation=ConfirmationObservation.AFFIRMATIVE,
            ),
        )
    )
    outcome = delta["outcome"]
    assert outcome is not None
    assert outcome.next_step is NextStep.EXECUTE_ACTION
    assert delta["dispatch"] is not None
    assert delta["dispatch"].action is Action.UNLOCK_ACCOUNT
    assert delta["dispatch"].challenge_id == "challenge-b"
    assert delta["confirmation"] is None


def test_affirmative_with_accidental_request_still_dispatches_once() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(NOW),
            confirmation=make_challenge(Action.UNLOCK_ACCOUNT, challenge_id="challenge-b"),
            model_decision=make_decision(
                confirmation_observation=ConfirmationObservation.AFFIRMATIVE,
                confirmation_request=True,
            ),
        )
    )
    outcome = delta["outcome"]
    assert outcome is not None
    assert outcome.next_step is NextStep.EXECUTE_ACTION
    assert delta["dispatch"] is not None
    assert delta["dispatch"].challenge_id == "challenge-b"
    # Consumed, never reopened in the same turn.
    assert delta["confirmation"] is None


def test_negative_never_dispatches_and_clears() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(NOW),
            confirmation=make_challenge(Action.UNLOCK_ACCOUNT),
            model_decision=make_decision(
                confirmation_observation=ConfirmationObservation.NEGATIVE,
            ),
        )
    )
    assert delta["dispatch"] is None
    assert delta["confirmation"] is None
    assert delta["goal"] is not None


def test_affirmation_without_challenge_dispatches_nothing() -> None:
    eligible = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(NOW),
            model_decision=make_decision(
                confirmation_observation=ConfirmationObservation.AFFIRMATIVE,
            ),
        )
    )
    assert eligible["dispatch"] is None
    assert eligible["external_operation"] is None

    ineligible = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(),
            model_decision=make_decision(
                confirmation_observation=ConfirmationObservation.AFFIRMATIVE,
            ),
        )
    )
    assert ineligible["dispatch"] is None
    assert ineligible["confirmation"] is None
    assert ineligible["outcome"] is not None
    assert ineligible["outcome"].message == SAFE_FALLBACK_MESSAGE


# --- stale contexts -------------------------------------------------------------


def test_old_unlock_challenge_cannot_dispatch_after_reset_turn() -> None:
    first = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT, revision=1),
            identity=make_identity(NOW),
            confirmation=make_challenge(Action.UNLOCK_ACCOUNT, revision=1),
            model_decision=make_decision(
                goal=GoalProposal(intent=GoalIntent.REQUEST, action=Action.RESET_PASSWORD),
            ),
        )
    )
    assert first["dispatch"] is None
    assert first["goal"] is not None
    assert first["goal"].action is Action.RESET_PASSWORD
    second = advance_turn(
        make_state(
            goal=first["goal"],
            identity=make_identity(NOW),
            confirmation=first["confirmation"],
            model_decision=make_decision(
                confirmation_observation=ConfirmationObservation.AFFIRMATIVE,
            ),
        )
    )
    assert second["dispatch"] is None
    assert second["external_operation"] is None
    if second["confirmation"] is not None:
        assert second["confirmation"].action is Action.RESET_PASSWORD


def test_revision_bump_invalidates_the_previous_challenge() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.RESET_PASSWORD, revision=1),
            identity=make_identity(NOW),
            confirmation=make_challenge(Action.RESET_PASSWORD, revision=1),
            model_decision=make_decision(
                goal=GoalProposal(intent=GoalIntent.CORRECT, action=Action.RESET_PASSWORD),
                confirmation_observation=ConfirmationObservation.AFFIRMATIVE,
            ),
        )
    )
    assert delta["dispatch"] is None
    assert delta["external_operation"] is None


def test_mode_switch_invalidates_before_any_affirmation() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.RESET_PASSWORD, assistance_mode=AssistanceMode.AUTONOMOUS),
            identity=make_identity(NOW),
            confirmation=make_challenge(Action.RESET_PASSWORD),
            model_decision=make_decision(
                assistance_mode=AssistanceMode.GUIDED,
                confirmation_observation=ConfirmationObservation.AFFIRMATIVE,
            ),
        )
    )
    assert delta["dispatch"] is None
    assert delta["confirmation"] is None


def test_revalidated_identity_invalidates_the_previous_challenge() -> None:
    from datetime import timedelta

    delta = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(NOW),
            confirmation=make_challenge(
                Action.UNLOCK_ACCOUNT, identity_validated_at=NOW - timedelta(minutes=5)
            ),
            model_decision=make_decision(
                confirmation_observation=ConfirmationObservation.AFFIRMATIVE,
            ),
        )
    )
    assert delta["dispatch"] is None
    assert delta["external_operation"] is None


def test_voice_failure_keeps_the_accepted_policy() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(NOW),
            confirmation=make_challenge(Action.UNLOCK_ACCOUNT),
            confirmation_event=ConfirmationEvent.ASR_TIMEOUT,
            model_decision=make_decision(route=Route.CONTINUE),
        )
    )
    assert delta["confirmation"] is None
    assert delta["dispatch"] is None
    assert delta["identity"].validated_at == NOW
    assert delta["identity"].caller_failures == 0


def test_replay_never_duplicates_the_operation() -> None:
    first = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(NOW),
            confirmation=make_challenge(Action.UNLOCK_ACCOUNT, challenge_id="challenge-1"),
            model_decision=make_decision(
                confirmation_observation=ConfirmationObservation.AFFIRMATIVE,
            ),
        )
    )
    assert first["dispatch"] is not None
    operation_id = first["dispatch"].operation_id
    second = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(NOW),
            confirmation=make_challenge(Action.UNLOCK_ACCOUNT, challenge_id="challenge-2"),
            dispatch=first["dispatch"],
            external_operation=first["external_operation"],
            model_decision=make_decision(
                confirmation_observation=ConfirmationObservation.AFFIRMATIVE,
            ),
        )
    )
    assert second["external_operation"] is not None
    assert second["external_operation"].operation_id == operation_id
    assert second["external_operation"].status is OperationStatus.PENDING


# --- P1 derivation properties ------------------------------------------------------


def test_p1_derives_choice_only_for_undecided_reset_without_consumable_challenge() -> None:
    obligation = derive_semantic_obligation(
        goal=make_goal(Action.RESET_PASSWORD, assistance_mode=AssistanceMode.UNDECIDED),
        identity=make_identity(NOW),
        confirmation=None,
        external_operation=None,
        password_presentation=None,
        now=NOW,
    )
    assert obligation.expected_user_response is ExpectedUserResponse.ASSISTANCE_MODE_CHOICE
    assert obligation.expected_action is Action.RESET_PASSWORD
    assert obligation.expected_goal_revision == 1


def test_p1_derives_confirmation_only_for_a_consumable_challenge() -> None:
    obligation = derive_semantic_obligation(
        goal=make_goal(Action.RESET_PASSWORD, assistance_mode=AssistanceMode.AUTONOMOUS),
        identity=make_identity(NOW),
        confirmation=make_challenge(Action.RESET_PASSWORD),
        external_operation=None,
        password_presentation=None,
        now=NOW,
    )
    assert obligation.expected_user_response is ExpectedUserResponse.ACTION_CONFIRMATION
    assert obligation.expected_action is Action.RESET_PASSWORD
    assert obligation.expected_goal_revision == 1


def test_p1_derives_none_otherwise() -> None:
    assert (
        derive_semantic_obligation(
            goal=None,
            identity=make_identity(NOW),
            confirmation=None,
            external_operation=None,
            password_presentation=None,
            now=NOW,
        ).expected_user_response
        is ExpectedUserResponse.NONE
    )
    assert (
        derive_semantic_obligation(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(NOW),
            confirmation=None,
            external_operation=None,
            password_presentation=None,
            now=NOW,
        ).expected_user_response
        is ExpectedUserResponse.NONE
    )
    assert (
        derive_semantic_obligation(
            goal=make_goal(Action.RESET_PASSWORD, assistance_mode=AssistanceMode.GUIDED),
            identity=make_identity(NOW),
            confirmation=None,
            external_operation=None,
            password_presentation=None,
            now=NOW,
        ).expected_user_response
        is ExpectedUserResponse.NONE
    )


def test_p1_ignores_transcript_keywords_and_carries_no_pii() -> None:
    base = derive_semantic_obligation(
        goal=make_goal(Action.RESET_PASSWORD, assistance_mode=AssistanceMode.UNDECIDED),
        identity=make_identity(NOW),
        confirmation=None,
        external_operation=None,
        password_presentation=None,
        now=NOW,
    )
    assert set(base.model_dump()) == {
        "expected_user_response",
        "expected_action",
        "expected_goal_revision",
    }
    assert render_semantic_obligation(base) is not None
    assert (
        render_semantic_obligation(
            SemanticObligationProjection(expected_user_response=ExpectedUserResponse.NONE)
        )
        is None
    )


def test_p1_side_effect_free_witnesses() -> None:
    import json

    from app.session.turns import TurnOutcomeState

    assert not hasattr(TurnOutcomeState, "expected_user_response")
    assert "semantic_obligation" not in TurnOutcomeState.model_fields
    obligation = derive_semantic_obligation(
        goal=make_goal(Action.RESET_PASSWORD, assistance_mode=AssistanceMode.UNDECIDED),
        identity=make_identity(NOW),
        confirmation=None,
        external_operation=None,
        password_presentation=None,
        now=NOW,
    )
    rendered = render_semantic_obligation(obligation)
    assert rendered is not None
    assert rendered.startswith("<semantic_obligation>")
    assert rendered.endswith("</semantic_obligation>")
    inner = rendered.removeprefix("<semantic_obligation>").removesuffix("</semantic_obligation>")
    payload = json.loads(inner)
    assert set(payload) == {
        "expected_user_response",
        "expected_action",
        "expected_goal_revision",
    }
    assert payload["expected_user_response"] == "ASSISTANCE_MODE_CHOICE"


def test_goal_focus_side_preserves_goal_without_forcing_identity() -> None:
    goal = make_goal(Action.UNLOCK_ACCOUNT)
    delta = advance_turn(
        make_state(
            goal=goal,
            model_decision=make_decision(route=Route.CONTINUE, goal_focus=GoalFocus.SIDE),
        )
    )
    assert delta["goal"] == goal
    assert delta["outcome"] is not None
    assert delta["outcome"].next_step is not None
