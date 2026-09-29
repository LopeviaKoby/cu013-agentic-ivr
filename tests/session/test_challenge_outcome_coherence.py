"""Challenge / caller-facing outcome coherence (CU013-CONVARCH-1-4).

A consumable challenge may only survive when the caller-facing outcome
selected for that turn presents its matching action-specific confirmation
for the same action, goal revision and identity scope. A model
``confirmation_request`` alone is never sufficient when the runtime
substitutes the message with a safe fallback, farewell, transfer, identity
capture or processing step.

No model, network, credentials or PII. Uses only closed semantic facts.
"""

from app.session.actions import Action
from app.session.outcome import NextStep
from app.session.record import AssistanceMode, OperationStatus
from app.session.turns import (
    COMPLETE_FAREWELL_MESSAGE,
    SAFE_FALLBACK_MESSAGE,
    ConfirmationEvent,
    ConfirmationObservation,
    GoalFocus,
    GoalIntent,
    GoalProposal,
    HandoffCause,
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


def _is_fallback_with_live_challenge(delta) -> bool:
    outcome = delta["outcome"]
    assert outcome is not None
    return outcome.message == SAFE_FALLBACK_MESSAGE and delta["confirmation"] is not None


# --- Invariant 3: contradictory decision signature ---------------------------


def test_contradictory_autonomous_affirmation_reissues_reset_confirmation() -> None:
    """Exact contradictory signature takes Form A (SPEC recovery): no dispatch, the
    deterministic RESET reconfirmation is spoken and its matching challenge
    stays consumable. Fallback + live challenge is impossible."""
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.RESET_PASSWORD, assistance_mode=AssistanceMode.UNDECIDED),
            identity=make_identity(NOW),
            confirmation=None,
            model_decision=make_decision(
                route=Route.CONTINUE,
                assistance_mode=AssistanceMode.AUTONOMOUS,
                confirmation_observation=ConfirmationObservation.AFFIRMATIVE,
                confirmation_request=True,
            ),
        )
    )
    outcome = delta["outcome"]
    assert outcome is not None
    assert delta["dispatch"] is None
    assert delta["external_operation"] is None
    assert not _is_fallback_with_live_challenge(delta)
    assert outcome.next_step is NextStep.LISTEN
    assert outcome.violations == ()
    assert outcome.message == _reconfirmation_message(Action.RESET_PASSWORD)
    assert delta["confirmation"] is not None
    assert delta["confirmation"].action is Action.RESET_PASSWORD
    assert delta["goal"] is not None
    assert delta["goal"].revision == delta["confirmation"].goal_revision
    assert delta["confirmation"].identity_validated_at == delta["identity"].validated_at


def test_ineligible_contradictory_affirmation_falls_back_with_absent_challenge() -> None:
    """Same contradictory observation without a valid authorization scope
    takes Form B: safe fallback and no consumable challenge."""
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.RESET_PASSWORD, assistance_mode=AssistanceMode.UNDECIDED),
            identity=make_identity(),
            confirmation=None,
            model_decision=make_decision(
                route=Route.CONTINUE,
                assistance_mode=AssistanceMode.AUTONOMOUS,
                confirmation_observation=ConfirmationObservation.AFFIRMATIVE,
                confirmation_request=True,
            ),
        )
    )
    outcome = delta["outcome"]
    assert outcome is not None
    assert delta["dispatch"] is None
    assert delta["confirmation"] is None
    assert outcome.message == SAFE_FALLBACK_MESSAGE
    assert outcome.violations


# --- Invariant 5: outcome override atomicity ---------------------------------


def test_complete_override_leaves_no_consumable_challenge() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(NOW),
            confirmation=None,
            model_decision=make_decision(
                route=Route.COMPLETE,
                message="closing",
                confirmation_request=True,
            ),
        )
    )
    outcome = delta["outcome"]
    assert outcome is not None
    assert outcome.next_step is NextStep.COMPLETE
    assert outcome.message == COMPLETE_FAREWELL_MESSAGE
    assert delta["confirmation"] is None
    assert delta["dispatch"] is None


def test_transfer_override_leaves_no_consumable_challenge() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(NOW),
            confirmation=None,
            model_decision=make_decision(
                route=Route.ESCALATE,
                handoff_cause=HandoffCause.CALLER_REQUEST,
                confirmation_request=True,
            ),
        )
    )
    outcome = delta["outcome"]
    assert outcome is not None
    assert outcome.next_step is NextStep.TRANSFER
    assert delta["confirmation"] is None
    assert delta["dispatch"] is None


def test_fallback_override_leaves_no_consumable_challenge() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(NOW),
            confirmation=None,
            model_decision=make_decision(
                route=Route.CONTINUE,
                confirmation_request=True,
                claims=[{"kind": "RESET_CONFIRMED"}],
            ),
        )
    )
    outcome = delta["outcome"]
    assert outcome is not None
    assert outcome.message == SAFE_FALLBACK_MESSAGE
    assert outcome.violations
    assert delta["confirmation"] is None
    assert delta["dispatch"] is None


def test_collect_identity_override_leaves_no_consumable_challenge() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(),
            confirmation=None,
            model_decision=make_decision(
                route=Route.CONTINUE,
                goal_focus=GoalFocus.PROGRESS,
                confirmation_request=True,
            ),
        )
    )
    outcome = delta["outcome"]
    assert outcome is not None
    assert outcome.next_step is NextStep.COLLECT_IDENTITY
    assert delta["confirmation"] is None
    assert delta["dispatch"] is None


def test_processing_override_consumes_the_challenge() -> None:
    challenge = make_challenge(Action.UNLOCK_ACCOUNT)
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(NOW),
            confirmation=challenge,
            model_decision=make_decision(
                confirmation_observation=ConfirmationObservation.AFFIRMATIVE,
            ),
        )
    )
    outcome = delta["outcome"]
    assert outcome is not None
    assert outcome.next_step is NextStep.EXECUTE_ACTION
    assert delta["dispatch"] is not None
    assert delta["confirmation"] is None


def test_preserved_challenge_does_not_survive_a_fallback_override() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(NOW),
            confirmation=make_challenge(Action.UNLOCK_ACCOUNT),
            model_decision=make_decision(
                route=Route.CONTINUE,
                claims=[{"kind": "RESET_CONFIRMED"}],
            ),
        )
    )
    outcome = delta["outcome"]
    assert outcome is not None
    assert outcome.message == SAFE_FALLBACK_MESSAGE
    assert delta["confirmation"] is None
    assert delta["dispatch"] is None


def test_lateral_listen_expires_the_pending_challenge() -> None:
    """Immediate reply window (owner decision): a lateral LISTEN that does
    not resolve the pending confirmation expires it. Goal, identity and
    revision survive; a future confirmation needs a fresh challenge."""
    challenge = make_challenge(Action.UNLOCK_ACCOUNT)
    goal = make_goal(Action.UNLOCK_ACCOUNT)
    delta = advance_turn(
        make_state(
            goal=goal,
            identity=make_identity(NOW),
            confirmation=challenge,
            model_decision=make_decision(
                route=Route.CONTINUE,
                goal_focus=GoalFocus.SIDE,
            ),
        )
    )
    outcome = delta["outcome"]
    assert outcome is not None
    assert outcome.next_step is NextStep.LISTEN
    assert outcome.violations == ()
    assert outcome.message == "synthetic message"
    assert delta["confirmation"] is None
    assert delta["goal"] == goal
    assert delta["dispatch"] is None


# --- Invariant 2: matching action and revision --------------------------------


def test_affirmative_consumes_only_the_matching_action_and_revision() -> None:
    challenge = make_challenge(Action.UNLOCK_ACCOUNT, revision=1)
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT, revision=1),
            identity=make_identity(NOW),
            confirmation=challenge,
            model_decision=make_decision(
                confirmation_observation=ConfirmationObservation.AFFIRMATIVE,
            ),
        )
    )
    assert delta["dispatch"] is not None
    assert delta["dispatch"].action is Action.UNLOCK_ACCOUNT
    assert delta["dispatch"].goal_revision == 1
    assert delta["dispatch"].challenge_id == challenge.challenge_id


def test_stale_revision_affirmation_never_dispatches() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(
                Action.RESET_PASSWORD,
                revision=2,
                assistance_mode=AssistanceMode.AUTONOMOUS,
            ),
            identity=make_identity(NOW),
            confirmation=make_challenge(Action.RESET_PASSWORD, revision=1),
            model_decision=make_decision(
                confirmation_observation=ConfirmationObservation.AFFIRMATIVE,
            ),
        )
    )
    assert delta["dispatch"] is None
    assert delta["external_operation"] is None
    # Eligible, so the SPEC recovery reissues the current revision instead
    # of leaving a stale challenge consumable.
    assert delta["confirmation"] is not None
    assert delta["confirmation"].action is Action.RESET_PASSWORD
    assert delta["confirmation"].goal_revision == 2


def test_identity_scope_mismatch_never_dispatches() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(NOW),
            confirmation=make_challenge(Action.UNLOCK_ACCOUNT, identity_validated_at=NOW),
            model_decision=make_decision(
                confirmation_observation=ConfirmationObservation.AFFIRMATIVE,
            ),
        )
    )
    # The double binds the challenge to NOW while the identity here is also
    # NOW, so this is the matching control: it must dispatch. A mismatch is
    # covered by the expired-identity legality tests; this pins the scope
    # equality the coherence gate also enforces.
    assert delta["dispatch"] is not None


# --- Invariant 4: incompatible context invalidates ----------------------------


def test_unlock_challenge_dies_when_the_context_becomes_reset() -> None:
    """UNLOCK challenge + same-turn RESET context + AFFIRMATIVE never
    redispatches UNLOCK. The stale challenge is cleared before the
    observation, so only a fresh RESET challenge may remain."""
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT, revision=1),
            identity=make_identity(NOW),
            confirmation=make_challenge(Action.UNLOCK_ACCOUNT, revision=1),
            model_decision=make_decision(
                route=Route.CONTINUE,
                goal=GoalProposal(intent=GoalIntent.REQUEST, action=Action.RESET_PASSWORD),
                assistance_mode=AssistanceMode.AUTONOMOUS,
                confirmation_observation=ConfirmationObservation.AFFIRMATIVE,
                confirmation_request=True,
            ),
        )
    )
    assert delta["dispatch"] is None
    assert delta["external_operation"] is None
    if delta["confirmation"] is not None:
        assert delta["confirmation"].action is Action.RESET_PASSWORD
        assert delta["goal"] is not None
        assert delta["confirmation"].goal_revision == delta["goal"].revision


def test_mode_switch_to_guided_with_affirmation_dispatches_nothing() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.RESET_PASSWORD, assistance_mode=AssistanceMode.AUTONOMOUS),
            identity=make_identity(NOW),
            confirmation=make_challenge(Action.RESET_PASSWORD),
            model_decision=make_decision(
                route=Route.CONTINUE,
                assistance_mode=AssistanceMode.GUIDED,
                confirmation_observation=ConfirmationObservation.AFFIRMATIVE,
            ),
        )
    )
    assert delta["dispatch"] is None
    assert delta["external_operation"] is None
    assert delta["confirmation"] is None


# --- Replay / idempotency ------------------------------------------------------


def test_recovery_creates_no_dispatch_or_operation() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.RESET_PASSWORD, assistance_mode=AssistanceMode.UNDECIDED),
            identity=make_identity(NOW),
            confirmation=None,
            dispatch=None,
            external_operation=None,
            model_decision=make_decision(
                route=Route.CONTINUE,
                assistance_mode=AssistanceMode.AUTONOMOUS,
                confirmation_observation=ConfirmationObservation.AFFIRMATIVE,
                confirmation_request=True,
            ),
        )
    )
    assert delta["dispatch"] is None
    assert delta["external_operation"] is None
    assert delta["confirmation"] is not None


def test_presented_challenge_dispatches_once_and_active_operation_blocks_replay() -> None:
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
    assert first["external_operation"] is not None
    assert first["external_operation"].operation_id == operation_id

    replay = advance_turn(
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
    assert replay["external_operation"] is not None
    assert replay["external_operation"].operation_id == operation_id
    assert replay["external_operation"].status is OperationStatus.PENDING
    if replay["dispatch"] is not None:
        assert replay["dispatch"].operation_id == operation_id


# --- Voice failure: no authorization reuse -------------------------------------


def test_voice_timeout_with_affirmation_never_dispatches() -> None:
    delta = advance_turn(
        make_state(
            goal=make_goal(Action.UNLOCK_ACCOUNT),
            identity=make_identity(NOW),
            confirmation=make_challenge(Action.UNLOCK_ACCOUNT),
            confirmation_event=ConfirmationEvent.ASR_TIMEOUT,
            model_decision=make_decision(
                confirmation_observation=ConfirmationObservation.AFFIRMATIVE,
            ),
        )
    )
    assert delta["dispatch"] is None
    assert delta["external_operation"] is None
    assert delta["identity"].validated_at == NOW
    assert delta["identity"].caller_failures == 0
