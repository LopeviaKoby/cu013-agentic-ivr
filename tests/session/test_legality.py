"""Deterministic legality tests for the semantic runtime (ADR-0010).

These tests encode the accepted properties without any model, network or
credential: conversational plan, identity TTL, confirmation challenge,
authorized dispatch, external-operation truth and the route/claim guard.
"""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from app.session.outcome import NextStep
from app.session.record import (
    IDENTITY_TTL,
    Action,
    DeliveryStatus,
    OperationStatus,
    PasswordPresentation,
    PlaybackVoice,
)
from app.session.turns import (
    SAFE_FALLBACK_MESSAGE,
    ClaimKind,
    ConfirmationEvent,
    ConfirmationObservation,
    ExternalEvent,
    ExternalEventKind,
    GoalFocus,
    GoalIntent,
    GoalProposal,
    HandoffCause,
    IdentityOutcome,
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


def _presentation(
    *,
    voice: PlaybackVoice = PlaybackVoice.PLAYBACK_RETURNED,
    caller_finished: bool = False,
) -> PasswordPresentation:
    """Synthetic presentation facts; never carries a password."""
    return PasswordPresentation(
        operation_id="operation-1",
        action=Action.RESET_PASSWORD,
        goal_revision=1,
        voice=voice,
        caller_finished=caller_finished,
        presented_at=NOW,
    )


def assert_fallback(delta) -> None:  # type: ignore[no-untyped-def]
    outcome = delta["outcome"]
    assert outcome is not None
    assert outcome.message == SAFE_FALLBACK_MESSAGE
    assert outcome.violations


# --- plan -------------------------------------------------------------------


def test_plan_registers_a_goal_before_identity() -> None:
    delta = advance_turn(
        make_state(
            model_decision=make_decision(
                route=Route.COLLECT_IDENTITY,
                goal=GoalProposal(intent=GoalIntent.REQUEST, action=Action.UNLOCK_ACCOUNT),
            )
        )
    )
    assert delta["goal"] is not None
    assert delta["goal"].action is Action.UNLOCK_ACCOUNT
    assert delta["goal"].revision == 1
    assert delta["identity"].validated_at is None
    assert delta["dispatch"] is None
    assert delta["external_operation"] is None
    assert delta["outcome"] is not None
    assert delta["outcome"].next_step is NextStep.COLLECT_IDENTITY


def test_ambiguous_intention_materializes_no_goal_and_listens() -> None:
    """A turn that resolves nothing must not create a supported goal.

    The semantic disambiguation belongs to the model; the runtime honors the
    absent goal: no plan, no identity capture, no confirmation, no dispatch
    and no external operation.
    """
    delta = advance_turn(make_state(model_decision=make_decision(route=Route.CONTINUE)))
    assert delta["goal"] is None
    assert delta["identity"].validated_at is None
    assert delta["confirmation"] is None
    assert delta["dispatch"] is None
    assert delta["external_operation"] is None
    assert delta["outcome"] is not None
    assert delta["outcome"].next_step is NextStep.LISTEN
    assert delta["outcome"].command is None


def test_direct_reset_request_collects_identity() -> None:
    delta = advance_turn(
        make_state(
            model_decision=make_decision(
                route=Route.CONTINUE,
                goal=GoalProposal(intent=GoalIntent.REQUEST, action=Action.RESET_PASSWORD),
                goal_focus=GoalFocus.PROGRESS,
            )
        )
    )
    assert delta["goal"] is not None
    assert delta["goal"].action is Action.RESET_PASSWORD
    assert delta["goal"].revision == 1
    assert delta["confirmation"] is None
    assert delta["dispatch"] is None
    assert delta["outcome"] is not None
    assert delta["outcome"].next_step is NextStep.COLLECT_IDENTITY


def test_goal_progress_preserves_the_goal_and_requires_identity() -> None:
    """A turn that advances the pending goal without authorization captures identity.

    The closed ``goal_focus`` signal overrides the residual CONTINUE proposal:
    the model message may answer the immediate need, but the runtime still asks
    XCALLY for the capability the state requires.
    """
    goal = make_goal(Action.UNLOCK_ACCOUNT)
    delta = advance_turn(
        make_state(
            goal=goal,
            model_decision=make_decision(route=Route.CONTINUE, goal_focus=GoalFocus.PROGRESS),
        )
    )
    assert delta["goal"] == goal
    assert delta["outcome"] is not None
    assert delta["outcome"].message == "synthetic message"
    assert delta["outcome"].next_step is NextStep.COLLECT_IDENTITY


def test_side_question_preserves_the_goal_and_listens() -> None:
    """An off-topic/lateral turn never forces authorization by itself.

    The goal stays pending for later, no identity capture is requested and the
    caller keeps the conversation open.
    """
    goal = make_goal(Action.UNLOCK_ACCOUNT)
    delta = advance_turn(
        make_state(
            goal=goal,
            model_decision=make_decision(route=Route.CONTINUE, goal_focus=GoalFocus.SIDE),
        )
    )
    assert delta["goal"] == goal
    assert delta["identity"].validated_at is None
    assert delta["dispatch"] is None
    assert delta["outcome"] is not None
    assert delta["outcome"].message == "synthetic message"
    assert delta["outcome"].next_step is NextStep.LISTEN


def test_reiterating_the_same_goal_does_not_bump_the_revision() -> None:
    goal = make_goal(Action.UNLOCK_ACCOUNT, revision=3)
    delta = advance_turn(
        make_state(
            goal=goal,
            model_decision=make_decision(
                goal=GoalProposal(intent=GoalIntent.REQUEST, action=Action.UNLOCK_ACCOUNT)
            ),
        )
    )
    assert delta["goal"] == goal


def test_goal_switch_bumps_the_revision_and_invalidates_the_challenge() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.RESET_PASSWORD, revision=2),
            confirmation=make_challenge(Action.RESET_PASSWORD, revision=2),
            model_decision=make_decision(
                goal=GoalProposal(intent=GoalIntent.REQUEST, action=Action.UNLOCK_ACCOUNT)
            ),
        )
    )
    assert delta["goal"].action is Action.UNLOCK_ACCOUNT  # type: ignore[union-attr]
    assert delta["goal"].revision == 3  # type: ignore[union-attr]
    assert delta["confirmation"] is None
    assert delta["dispatch"] is None


def test_goal_correction_bumps_the_revision_and_invalidates_the_challenge() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.RESET_PASSWORD, revision=1),
            confirmation=make_challenge(Action.RESET_PASSWORD, revision=1),
            model_decision=make_decision(
                goal=GoalProposal(intent=GoalIntent.CORRECT, action=Action.RESET_PASSWORD)
            ),
        )
    )
    assert delta["goal"].action is Action.RESET_PASSWORD  # type: ignore[union-attr]
    assert delta["goal"].revision == 2  # type: ignore[union-attr]
    assert delta["confirmation"] is None


def test_goal_cancellation_clears_the_plan_and_the_challenge() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            confirmation=make_challenge(Action.UNLOCK_ACCOUNT),
            model_decision=make_decision(
                route=Route.COMPLETE, goal=GoalProposal(intent=GoalIntent.CANCEL)
            ),
        )
    )
    assert delta["goal"] is None
    assert delta["confirmation"] is None
    assert delta["dispatch"] is None
    assert delta["outcome"] is not None
    assert delta["outcome"].next_step is NextStep.COMPLETE


def test_two_supported_goals_are_representable_sequentially() -> None:
    first = advance_turn(
        make_state(
            model_decision=make_decision(
                route=Route.COLLECT_IDENTITY,
                goal=GoalProposal(intent=GoalIntent.REQUEST, action=Action.RESET_PASSWORD),
            )
        )
    )
    assert first["goal"] is not None
    assert first["goal"].action is Action.RESET_PASSWORD
    second = advance_turn(
        make_state(
            goal=first["goal"],
            model_decision=make_decision(
                goal=GoalProposal(intent=GoalIntent.REQUEST, action=Action.UNLOCK_ACCOUNT)
            ),
        )
    )
    assert second["goal"] is not None
    assert second["goal"].action is Action.UNLOCK_ACCOUNT


def test_unsupported_goal_is_rejected_by_the_closed_contract() -> None:
    with pytest.raises(ValidationError):
        make_decision(goal={"intent": "REQUEST", "action": "DELETE_ACCOUNT"})


def test_goal_proposal_without_an_action_falls_back_safely() -> None:
    delta = advance_turn(make_state(model_decision=make_decision(goal={"intent": "REQUEST"})))
    assert_fallback(delta)


# --- identity ---------------------------------------------------------------


def test_valid_identity_enables_eligibility_but_not_dispatch() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(NOW - timedelta(minutes=29)),
            model_decision=make_decision(route=Route.CONTINUE),
        )
    )
    assert delta["dispatch"] is None
    assert delta["external_operation"] is None


def test_expired_identity_requires_revalidation_and_blocks_dispatch() -> None:
    revalidation = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(NOW - IDENTITY_TTL),
            model_decision=make_decision(route=Route.COLLECT_IDENTITY),
        )
    )
    assert revalidation["outcome"] is not None
    assert revalidation["outcome"].next_step is NextStep.COLLECT_IDENTITY
    assert revalidation["outcome"].violations == ()

    expired_affirmation = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(NOW - IDENTITY_TTL),
            confirmation=make_challenge(Action.UNLOCK_ACCOUNT, identity_validated_at=NOW),
            model_decision=make_decision(
                confirmation_observation=ConfirmationObservation.AFFIRMATIVE,
                goal_focus=GoalFocus.PROGRESS,
            ),
        )
    )
    assert expired_affirmation["dispatch"] is None
    assert expired_affirmation["external_operation"] is None
    assert_fallback(expired_affirmation)
    # The expired authorization leaves the goal pending, so the runtime
    # requires a fresh identity capture instead of staying silent.
    assert expired_affirmation["outcome"] is not None
    assert expired_affirmation["outcome"].next_step is NextStep.COLLECT_IDENTITY


def test_third_caller_failure_forces_escalation() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(failures=2),
            identity_outcome=IdentityOutcome.CALLER_FAILURE,
            model_decision=make_decision(route=Route.COLLECT_IDENTITY),
        )
    )
    assert delta["identity"].caller_failures == 3
    assert delta["identity"].requires_handoff()
    assert delta["outcome"] is not None
    assert delta["outcome"].next_step is NextStep.TRANSFER


def test_technical_identity_failure_does_not_consume_an_attempt() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(failures=1),
            identity_outcome=IdentityOutcome.TECHNICAL_FAILURE,
            model_decision=make_decision(route=Route.CONTINUE, goal_focus=GoalFocus.PROGRESS),
        )
    )
    assert delta["identity"].caller_failures == 1
    assert delta["outcome"] is not None
    assert delta["outcome"].next_step is NextStep.COLLECT_IDENTITY


def test_technical_identity_failure_never_escalates_by_itself() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(failures=2),
            identity_outcome=IdentityOutcome.TECHNICAL_FAILURE,
            model_decision=make_decision(route=Route.COLLECT_IDENTITY),
        )
    )
    assert delta["identity"].caller_failures == 2
    assert not delta["identity"].requires_handoff()
    assert delta["dispatch"] is None
    assert delta["external_operation"] is None
    assert delta["outcome"] is not None
    assert delta["outcome"].next_step is NextStep.COLLECT_IDENTITY


def test_validation_replaces_the_authorization_and_clears_the_failure_counter() -> None:
    delta = advance_turn(
        make_state(
            identity=make_identity(failures=1),
            identity_outcome=IdentityOutcome.VALIDATED,
            model_decision=make_decision(route=Route.CONTINUE),
        )
    )
    assert delta["identity"].validated_at == NOW
    # A positive validation resolves the phase, so stale caller failures never
    # carry over to a later, fresh attempt in the same call.
    assert delta["identity"].caller_failures == 0


def test_failed_attempt_never_downgrades_a_validated_identity() -> None:
    delta = advance_turn(
        make_state(
            identity=make_identity(NOW - timedelta(minutes=5)),
            identity_outcome=IdentityOutcome.CALLER_FAILURE,
            model_decision=make_decision(route=Route.CONTINUE),
        )
    )
    assert delta["identity"].validated_at == NOW - timedelta(minutes=5)
    assert delta["identity"].caller_failures == 1


def test_identity_projection_holds_no_pii_fields() -> None:
    delta = advance_turn(
        make_state(
            identity_outcome=IdentityOutcome.VALIDATED,
            model_decision=make_decision(route=Route.CONTINUE),
        )
    )
    rendered = repr(delta["identity"])
    assert set(delta["identity"].model_dump()) == {"validated_at", "caller_failures"}
    for sentinel in ("SYNTHETIC-DOC-0000", "1900-01-01-SYNTHETIC", "SYNTHETIC-DTMF-0000"):
        assert sentinel not in rendered


# --- confirmation -----------------------------------------------------------


def test_affirmative_with_a_valid_challenge_authorizes_the_dispatch() -> None:
    challenge = make_challenge(Action.UNLOCK_ACCOUNT)
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(NOW),
            confirmation=challenge,
            model_decision=make_decision(
                confirmation_observation=ConfirmationObservation.AFFIRMATIVE,
                claims=[{"kind": "ACTION_AUTHORIZED"}],
            ),
        )
    )
    assert delta["dispatch"] is not None
    assert delta["dispatch"].action is Action.UNLOCK_ACCOUNT
    assert delta["dispatch"].challenge_id == challenge.challenge_id
    assert delta["dispatch"].goal_revision == challenge.goal_revision
    assert delta["external_operation"] is not None
    assert delta["external_operation"].status is OperationStatus.PENDING
    assert delta["external_operation"].operation_id == delta["dispatch"].operation_id
    assert delta["confirmation"] is None
    assert delta["outcome"] is not None
    assert delta["outcome"].violations == ()


def test_negation_never_authorizes_and_keeps_the_goal() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(NOW),
            confirmation=make_challenge(Action.UNLOCK_ACCOUNT),
            model_decision=make_decision(
                confirmation_observation=ConfirmationObservation.NEGATIVE,
                claims=[{"kind": "ACTION_AUTHORIZED"}],
            ),
        )
    )
    assert delta["dispatch"] is None
    assert delta["external_operation"] is None
    assert delta["goal"] is not None
    assert delta["confirmation"] is None
    assert_fallback(delta)


def test_ambiguous_capture_never_authorizes_and_keeps_eligibility() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(NOW),
            confirmation=make_challenge(Action.UNLOCK_ACCOUNT),
            model_decision=make_decision(
                confirmation_observation=ConfirmationObservation.AMBIGUOUS
            ),
        )
    )
    assert delta["dispatch"] is None
    assert delta["confirmation"] is None
    assert delta["outcome"] is not None
    assert delta["outcome"].violations == ()


def test_timeout_or_silence_invalidates_the_attempt_without_touching_identity() -> None:
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


def test_stale_challenge_for_an_older_revision_never_authorizes() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.RESET_PASSWORD, revision=2),
            identity=make_identity(NOW),
            confirmation=make_challenge(Action.RESET_PASSWORD, revision=1),
            model_decision=make_decision(
                confirmation_observation=ConfirmationObservation.AFFIRMATIVE
            ),
        )
    )
    assert delta["dispatch"] is None
    assert delta["external_operation"] is None
    assert delta["confirmation"] is None
    assert delta["outcome"] is not None
    assert delta["outcome"].next_step is NextStep.LISTEN


def test_stale_challenge_is_repaired_even_without_a_model_decision() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.RESET_PASSWORD, revision=2),
            identity=make_identity(NOW),
            confirmation=make_challenge(Action.RESET_PASSWORD, revision=1),
        )
    )
    assert delta["confirmation"] is None
    assert delta["dispatch"] is None
    assert delta["outcome"] is None


def test_challenge_for_another_action_never_authorizes() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.RESET_PASSWORD),
            identity=make_identity(NOW),
            confirmation=make_challenge(Action.UNLOCK_ACCOUNT),
            model_decision=make_decision(
                confirmation_observation=ConfirmationObservation.AFFIRMATIVE
            ),
        )
    )
    assert delta["dispatch"] is None
    assert delta["external_operation"] is None
    assert delta["confirmation"] is None


def test_explicit_cancellation_cancels_the_action_and_the_challenge() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(NOW),
            confirmation=make_challenge(Action.UNLOCK_ACCOUNT),
            model_decision=make_decision(
                route=Route.COMPLETE,
                confirmation_observation=ConfirmationObservation.CANCEL,
            ),
        )
    )
    assert delta["goal"] is None
    assert delta["confirmation"] is None
    assert delta["dispatch"] is None
    assert delta["outcome"] is not None
    assert delta["outcome"].next_step is NextStep.COMPLETE
    assert delta["outcome"].violations == ()


def test_a_previous_affirmation_never_repeats_the_side_effect() -> None:
    first = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(NOW),
            confirmation=make_challenge(Action.UNLOCK_ACCOUNT),
            model_decision=make_decision(
                confirmation_observation=ConfirmationObservation.AFFIRMATIVE
            ),
        )
    )
    assert first["dispatch"] is not None
    second = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(NOW),
            dispatch=first["dispatch"],
            external_operation=first["external_operation"],
            confirmation=make_challenge(Action.UNLOCK_ACCOUNT, challenge_id="challenge-2"),
            model_decision=make_decision(
                confirmation_observation=ConfirmationObservation.AFFIRMATIVE
            ),
        )
    )
    assert second["external_operation"] is not None
    assert second["external_operation"].operation_id == first["dispatch"].operation_id
    assert second["external_operation"].status is OperationStatus.PENDING


def test_confirmation_challenge_is_only_opened_when_the_caller_is_eligible() -> None:
    eligible = advance_turn(
        make_state(
            goal=make_goal(Action.RESET_PASSWORD),
            identity=make_identity(NOW),
            model_decision=make_decision(confirmation_request=True),
        )
    )
    assert eligible["confirmation"] is not None
    assert eligible["confirmation"].action is Action.RESET_PASSWORD
    assert eligible["confirmation"].identity_validated_at == NOW

    ineligible = advance_turn(
        make_state(
            goal=make_goal(Action.RESET_PASSWORD),
            model_decision=make_decision(confirmation_request=True),
        )
    )
    assert ineligible["confirmation"] is None
    assert ineligible["outcome"] is not None
    assert ineligible["outcome"].violations == ()


def test_side_question_opens_no_challenge_even_with_valid_identity() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.RESET_PASSWORD),
            identity=make_identity(NOW),
            model_decision=make_decision(route=Route.CONTINUE),
        )
    )
    assert delta["goal"] is not None
    assert delta["confirmation"] is None
    assert delta["dispatch"] is None
    assert delta["outcome"] is not None
    assert delta["outcome"].next_step is NextStep.LISTEN


def test_invalidated_challenge_is_replaced_by_a_new_one() -> None:
    invalidated = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(NOW),
            confirmation=make_challenge(
                Action.UNLOCK_ACCOUNT, revision=1, challenge_id="challenge-1"
            ),
            confirmation_event=ConfirmationEvent.ASR_TIMEOUT,
        )
    )
    assert invalidated["confirmation"] is None
    replacement = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT, revision=2),
            identity=make_identity(NOW),
            confirmation=None,
            model_decision=make_decision(confirmation_request=True),
        )
    )
    challenge = replacement["confirmation"]
    assert challenge is not None
    assert challenge.challenge_id != "challenge-1"
    assert challenge.action is Action.UNLOCK_ACCOUNT
    assert challenge.goal_revision == 2
    assert challenge.identity_validated_at == NOW


# --- authorized dispatch ----------------------------------------------------


def test_dispatch_without_identity_is_blocked_and_identity_is_requested() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            confirmation=make_challenge(Action.UNLOCK_ACCOUNT, identity_validated_at=NOW),
            model_decision=make_decision(
                confirmation_observation=ConfirmationObservation.AFFIRMATIVE,
                goal_focus=GoalFocus.PROGRESS,
            ),
        )
    )
    assert delta["dispatch"] is None
    assert delta["external_operation"] is None
    assert_fallback(delta)
    assert delta["outcome"] is not None
    assert delta["outcome"].next_step is NextStep.COLLECT_IDENTITY


def test_dispatch_without_a_challenge_is_blocked() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(NOW),
            model_decision=make_decision(
                confirmation_observation=ConfirmationObservation.AFFIRMATIVE
            ),
        )
    )
    assert delta["dispatch"] is None
    assert delta["external_operation"] is None
    assert delta["outcome"] is not None
    assert delta["outcome"].violations == ()


def test_dispatch_with_an_active_operation_is_blocked() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(NOW),
            confirmation=make_challenge(Action.UNLOCK_ACCOUNT),
            external_operation=make_operation(Action.UNLOCK_ACCOUNT, OperationStatus.PENDING),
            model_decision=make_decision(
                confirmation_observation=ConfirmationObservation.AFFIRMATIVE
            ),
        )
    )
    assert delta["dispatch"] is None
    assert delta["external_operation"] is not None
    assert delta["external_operation"].status is OperationStatus.PENDING
    assert_fallback(delta)


def test_dispatch_is_blocked_while_the_operation_result_is_unknown() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(NOW),
            confirmation=make_challenge(Action.UNLOCK_ACCOUNT),
            external_operation=make_operation(Action.UNLOCK_ACCOUNT, OperationStatus.UNKNOWN),
            model_decision=make_decision(
                confirmation_observation=ConfirmationObservation.AFFIRMATIVE
            ),
        )
    )
    assert delta["dispatch"] is None
    assert delta["external_operation"] is not None
    assert delta["external_operation"].status is OperationStatus.UNKNOWN
    assert_fallback(delta)


def test_a_new_operation_is_possible_after_a_terminal_result() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(NOW),
            confirmation=make_challenge(Action.UNLOCK_ACCOUNT),
            dispatch=make_dispatch(Action.UNLOCK_ACCOUNT),
            external_operation=make_operation(Action.UNLOCK_ACCOUNT, OperationStatus.CONFIRMED),
            model_decision=make_decision(
                confirmation_observation=ConfirmationObservation.AFFIRMATIVE
            ),
        )
    )
    assert delta["dispatch"] is not None
    assert delta["dispatch"].challenge_id == "challenge-1"


# --- external operation truth -----------------------------------------------


def test_pending_operation_never_claims_success() -> None:
    delta = advance_turn(
        make_state(
            external_operation=make_operation(Action.UNLOCK_ACCOUNT, OperationStatus.PENDING),
            model_decision=make_decision(
                route=Route.COMPLETE, claims=[{"kind": "OPERATION_SUCCEEDED"}]
            ),
        )
    )
    assert_fallback(delta)


def test_uncertain_dispatch_moves_the_operation_to_unknown() -> None:
    delta = advance_turn(
        make_state(
            external_operation=make_operation(Action.UNLOCK_ACCOUNT, OperationStatus.PENDING),
            external_event=ExternalEvent(
                kind=ExternalEventKind.DISPATCH_UNKNOWN, operation_id="operation-1"
            ),
            model_decision=make_decision(route=Route.CONTINUE),
        )
    )
    assert delta["external_operation"] is not None
    assert delta["external_operation"].status is OperationStatus.UNKNOWN


def test_confirmed_result_is_reconciled_with_the_existing_operation() -> None:
    delta = advance_turn(
        make_state(
            external_operation=make_operation(Action.UNLOCK_ACCOUNT, OperationStatus.UNKNOWN),
            external_event=ExternalEvent(
                kind=ExternalEventKind.LATE_RESULT,
                operation_id="operation-1",
                status=OperationStatus.CONFIRMED,
            ),
            model_decision=make_decision(route=Route.CONTINUE),
        )
    )
    assert delta["external_operation"] is not None
    assert delta["external_operation"].operation_id == "operation-1"
    assert delta["external_operation"].status is OperationStatus.CONFIRMED


def test_failed_result_is_reconciled_without_success_wording() -> None:
    delta = advance_turn(
        make_state(
            external_operation=make_operation(Action.UNLOCK_ACCOUNT, OperationStatus.PENDING),
            external_event=ExternalEvent(
                kind=ExternalEventKind.RESULT,
                operation_id="operation-1",
                status=OperationStatus.FAILED,
            ),
            model_decision=make_decision(
                route=Route.CONTINUE, claims=[{"kind": "OPERATION_SUCCEEDED"}]
            ),
        )
    )
    assert delta["external_operation"] is not None
    assert delta["external_operation"].status is OperationStatus.FAILED
    assert_fallback(delta)


def test_duplicate_result_never_creates_a_new_operation() -> None:
    first = advance_turn(
        make_state(
            external_operation=make_operation(Action.UNLOCK_ACCOUNT, OperationStatus.CONFIRMED),
            external_event=ExternalEvent(
                kind=ExternalEventKind.RESULT,
                operation_id="operation-1",
                status=OperationStatus.CONFIRMED,
            ),
            model_decision=make_decision(
                route=Route.COMPLETE, claims=[{"kind": "OPERATION_SUCCEEDED"}]
            ),
        )
    )
    assert first["external_operation"] is not None
    assert first["external_operation"].operation_id == "operation-1"
    assert first["external_operation"].status is OperationStatus.CONFIRMED
    assert first["outcome"] is not None
    assert first["outcome"].violations == ()


def test_unmatched_result_only_reconciles_with_the_existing_operation() -> None:
    delta = advance_turn(
        make_state(
            external_operation=make_operation(Action.UNLOCK_ACCOUNT, OperationStatus.PENDING),
            external_event=ExternalEvent(
                kind=ExternalEventKind.RESULT,
                operation_id="operation-other",
                status=OperationStatus.CONFIRMED,
            ),
            model_decision=make_decision(route=Route.CONTINUE),
        )
    )
    assert delta["external_operation"] is not None
    assert delta["external_operation"].operation_id == "operation-1"
    assert delta["external_operation"].status is OperationStatus.PENDING


def test_delivery_is_a_separate_fact_from_the_reset_result() -> None:
    confirmed = advance_turn(
        make_state(
            external_operation=make_operation(Action.RESET_PASSWORD, OperationStatus.CONFIRMED),
            password_presentation=_presentation(caller_finished=True),
            model_decision=make_decision(
                route=Route.CONTINUE, claims=[{"kind": "DELIVERY_CONFIRMED"}]
            ),
        )
    )
    assert confirmed["external_operation"] is not None
    assert confirmed["external_operation"].status is OperationStatus.CONFIRMED
    assert confirmed["external_operation"].delivery is None
    assert_fallback(confirmed)

    delivered = advance_turn(
        make_state(
            external_operation=make_operation(Action.RESET_PASSWORD, OperationStatus.CONFIRMED),
            password_presentation=_presentation(caller_finished=True),
            external_event=ExternalEvent(
                kind=ExternalEventKind.DELIVERY,
                operation_id="operation-1",
                delivery=DeliveryStatus.CONFIRMED,
            ),
            model_decision=make_decision(
                route=Route.CONTINUE,
                claims=[{"kind": "RESET_CONFIRMED"}, {"kind": "DELIVERY_CONFIRMED"}],
            ),
        )
    )
    assert delivered["external_operation"] is not None
    assert delivered["external_operation"].delivery is DeliveryStatus.CONFIRMED
    assert delivered["outcome"] is not None
    assert delivered["outcome"].violations == ()


def test_unknown_result_does_not_redispatch() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(NOW),
            confirmation=make_challenge(Action.UNLOCK_ACCOUNT),
            dispatch=make_dispatch(Action.UNLOCK_ACCOUNT),
            external_operation=make_operation(Action.UNLOCK_ACCOUNT, OperationStatus.UNKNOWN),
            model_decision=make_decision(
                confirmation_observation=ConfirmationObservation.AFFIRMATIVE
            ),
        )
    )
    assert delta["external_operation"] is not None
    assert delta["external_operation"].status is OperationStatus.UNKNOWN
    assert delta["external_operation"].operation_id == "operation-1"


# --- route and claim guard --------------------------------------------------


def test_invented_success_claim_is_rejected() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(NOW),
            model_decision=make_decision(
                route=Route.COMPLETE, claims=[{"kind": "OPERATION_SUCCEEDED"}]
            ),
        )
    )
    assert_fallback(delta)


def test_invented_delivery_claim_is_rejected() -> None:
    delta = advance_turn(
        make_state(
            external_operation=make_operation(Action.RESET_PASSWORD, OperationStatus.CONFIRMED),
            password_presentation=_presentation(caller_finished=True),
            model_decision=make_decision(
                route=Route.COMPLETE, claims=[{"kind": "DELIVERY_CONFIRMED"}]
            ),
        )
    )
    assert_fallback(delta)


def test_invented_identity_claim_is_rejected() -> None:
    delta = advance_turn(
        make_state(model_decision=make_decision(claims=[{"kind": "IDENTITY_VALID"}]))
    )
    assert_fallback(delta)


def test_authorization_claim_needs_a_durable_dispatch() -> None:
    unbacked = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(NOW),
            model_decision=make_decision(claims=[{"kind": "ACTION_AUTHORIZED"}]),
        )
    )
    assert_fallback(unbacked)
    backed = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(NOW),
            dispatch=make_dispatch(Action.UNLOCK_ACCOUNT),
            model_decision=make_decision(claims=[{"kind": "ACTION_AUTHORIZED"}]),
        )
    )
    assert backed["outcome"] is not None
    assert backed["outcome"].violations == ()


def test_sensitivity_only_escalation_is_rejected() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.RESET_PASSWORD),
            identity=make_identity(NOW),
            model_decision=make_decision(
                route=Route.ESCALATE, handoff_cause=HandoffCause.TERMINAL_FAILURE
            ),
        )
    )
    assert_fallback(delta)


def test_caller_requested_handoff_is_permitted() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.RESET_PASSWORD),
            identity=make_identity(NOW),
            model_decision=make_decision(
                route=Route.ESCALATE, handoff_cause=HandoffCause.CALLER_REQUEST
            ),
        )
    )
    assert delta["outcome"] is not None
    assert delta["outcome"].next_step is NextStep.TRANSFER
    assert delta["outcome"].violations == ()


def test_terminal_failure_handoff_needs_a_terminal_failure() -> None:
    delta = advance_turn(
        make_state(
            external_operation=make_operation(Action.UNLOCK_ACCOUNT, OperationStatus.FAILED),
            model_decision=make_decision(
                route=Route.ESCALATE, handoff_cause=HandoffCause.TERMINAL_FAILURE
            ),
        )
    )
    assert delta["outcome"] is not None
    assert delta["outcome"].next_step is NextStep.TRANSFER
    assert delta["outcome"].violations == ()


def test_unsupported_operation_is_never_a_handoff_cause() -> None:
    with pytest.raises(ValidationError):
        make_decision(route=Route.ESCALATE, handoff_cause="UNSUPPORTED_OPERATION")
    unbacked = advance_turn(
        make_state(
            goal=make_goal(Action.RESET_PASSWORD),
            identity=make_identity(NOW),
            model_decision=make_decision(route=Route.ESCALATE),
        )
    )
    assert_fallback(unbacked)


def test_explicit_human_request_escalates_without_clearing_the_goal() -> None:
    goal = make_goal(Action.RESET_PASSWORD)
    delta = advance_turn(
        make_state(
            goal=goal,
            identity=make_identity(NOW),
            model_decision=make_decision(
                route=Route.ESCALATE, handoff_cause=HandoffCause.CALLER_REQUEST
            ),
        )
    )
    assert delta["goal"] == goal
    assert delta["confirmation"] is None
    assert delta["dispatch"] is None
    assert delta["outcome"] is not None
    assert delta["outcome"].next_step is NextStep.TRANSFER
    assert delta["outcome"].violations == ()


def test_cancellation_with_human_request_clears_the_goal_explicitly() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(NOW),
            confirmation=make_challenge(Action.UNLOCK_ACCOUNT),
            model_decision=make_decision(
                route=Route.ESCALATE,
                handoff_cause=HandoffCause.CALLER_REQUEST,
                confirmation_observation=ConfirmationObservation.CANCEL,
            ),
        )
    )
    assert delta["goal"] is None
    assert delta["confirmation"] is None
    assert delta["dispatch"] is None
    assert delta["outcome"] is not None
    assert delta["outcome"].next_step is NextStep.TRANSFER
    assert delta["outcome"].violations == ()


def test_collect_identity_needs_a_supported_goal_and_no_identity() -> None:
    legal = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            model_decision=make_decision(route=Route.COLLECT_IDENTITY),
        )
    )
    assert legal["outcome"] is not None
    assert legal["outcome"].next_step is NextStep.COLLECT_IDENTITY

    without_goal = advance_turn(
        make_state(model_decision=make_decision(route=Route.COLLECT_IDENTITY))
    )
    assert_fallback(without_goal)

    already_validated = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(NOW),
            model_decision=make_decision(route=Route.COLLECT_IDENTITY),
        )
    )
    assert_fallback(already_validated)


def test_complete_cannot_close_an_unfinished_operation() -> None:
    delta = advance_turn(
        make_state(
            external_operation=make_operation(Action.UNLOCK_ACCOUNT, OperationStatus.PENDING),
            model_decision=make_decision(route=Route.COMPLETE),
        )
    )
    assert_fallback(delta)


def test_complete_cannot_close_a_reset_before_it_is_presented() -> None:
    delta = advance_turn(
        make_state(
            external_operation=make_operation(Action.RESET_PASSWORD, OperationStatus.CONFIRMED),
            model_decision=make_decision(route=Route.COMPLETE),
        )
    )
    # The presentation is still owed: the runtime keeps the lifecycle open and
    # never closes the conversation on a COMPLETE proposal.
    assert delta["outcome"] is not None
    assert delta["outcome"].next_step is NextStep.LISTEN


def test_complete_is_permitted_once_the_reset_password_was_presented() -> None:
    delta = advance_turn(
        make_state(
            external_operation=make_operation(Action.RESET_PASSWORD, OperationStatus.CONFIRMED),
            password_presentation=_presentation(caller_finished=True),
            model_decision=make_decision(route=Route.COMPLETE),
        )
    )
    assert delta["outcome"] is not None
    assert delta["outcome"].next_step is NextStep.COMPLETE


def test_complete_is_permitted_after_a_failed_playback() -> None:
    delta = advance_turn(
        make_state(
            external_operation=make_operation(Action.RESET_PASSWORD, OperationStatus.CONFIRMED),
            password_presentation=_presentation(
                voice=PlaybackVoice.PRESENTATION_FAILED_BEFORE_PLAYBACK,
                caller_finished=True,
            ),
            model_decision=make_decision(route=Route.COMPLETE),
        )
    )
    assert delta["outcome"] is not None
    assert delta["outcome"].next_step is NextStep.COMPLETE


def test_complete_is_permitted_after_a_confirmed_unlock() -> None:
    delta = advance_turn(
        make_state(
            external_operation=make_operation(Action.UNLOCK_ACCOUNT, OperationStatus.CONFIRMED),
            model_decision=make_decision(
                route=Route.COMPLETE, claims=[{"kind": "OPERATION_SUCCEEDED"}]
            ),
        )
    )
    assert delta["outcome"] is not None
    assert delta["outcome"].next_step is NextStep.COMPLETE
    assert delta["outcome"].violations == ()


def test_third_failure_forces_escalation_over_any_model_route() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(failures=2),
            identity_outcome=IdentityOutcome.CALLER_FAILURE,
            model_decision=make_decision(route=Route.CONTINUE, claims=[{"kind": "IDENTITY_VALID"}]),
        )
    )
    assert delta["outcome"] is not None
    assert delta["outcome"].next_step is NextStep.TRANSFER
    assert "unbacked claim IDENTITY_VALID" in delta["outcome"].violations


def test_claim_kinds_cover_the_accepted_business_facts() -> None:
    assert {kind.value for kind in ClaimKind} == {
        "IDENTITY_VALID",
        "ACTION_AUTHORIZED",
        "OPERATION_SUCCEEDED",
        "OPERATION_FAILED",
        "RESET_CONFIRMED",
        "DELIVERY_CONFIRMED",
    }
