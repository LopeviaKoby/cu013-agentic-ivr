"""Deterministic regressions from E2E Ivr02-1790603869.7395.

The caller selected AUTONOMOUS, then an ambiguous/noisy turn proposed
UNDECIDED and the runtime downgraded the mode and cleared the challenge,
so the later affirmation could not dispatch. These tests pin the invariant:
an established GUIDED/AUTONOMOUS reset never degrades to UNDECIDED, and an
ambiguous confirmation invalidates the challenge but a fresh specific
confirmation recovers the dispatch.
"""

from app.session.actions import Action
from app.session.outcome import NextStep
from app.session.record import AssistanceMode, OperationStatus
from app.session.turns import (
    SAFE_FALLBACK_MESSAGE,
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


def _autonomous_state(**overrides: object):  # type: ignore[no-untyped-def]
    # Pure mode fixture: no prior AD mutation, so the temporary one-mutation
    # fail-safe never interferes with mode-persistence assertions. Sequential
    # UNLOCK->RESET behaviour lives in test_ad_mutation_fail_safe.py.
    values: dict[str, object] = {
        "goal": make_goal(Action.RESET_PASSWORD, assistance_mode=AssistanceMode.AUTONOMOUS),
        "identity": make_identity(NOW),
        "confirmation": make_challenge(Action.RESET_PASSWORD, challenge_id="reset-challenge"),
        "dispatch": None,
        "external_operation": None,
    }
    values.update(overrides)
    return make_state(**values)


def test_explicit_undecided_never_downgrades_an_established_mode() -> None:
    """A noisy turn proposing UNDECIDED must not undo the caller's choice."""
    delta = advance_turn(
        _autonomous_state(
            model_decision=make_decision(
                route=Route.CONTINUE,
                message=(
                    "Para confirmar el restablecimiento, indícame si deseas "
                    "que lo ejecute o prefieres guía."
                ),
                assistance_mode=AssistanceMode.UNDECIDED,
            )
        )
    )
    assert delta["goal"] is not None
    assert delta["goal"].assistance_mode is AssistanceMode.AUTONOMOUS
    # Immediate reply window: the noisy turn answers nothing, so the pending
    # RESET challenge expires instead of surviving unseen. The mode choice
    # itself is never downgraded.
    assert delta["confirmation"] is None
    # No prior mutation in this fixture, so no dispatch exists yet.
    assert delta["dispatch"] is None


def test_affirmative_with_an_established_autonomous_mode_dispatches_reset() -> None:
    delta = advance_turn(
        _autonomous_state(
            model_decision=make_decision(
                route=Route.CONTINUE,
                confirmation_observation=ConfirmationObservation.AFFIRMATIVE,
            )
        )
    )
    assert delta["goal"] is not None
    assert delta["goal"].assistance_mode is AssistanceMode.AUTONOMOUS
    assert delta["dispatch"] is not None
    assert delta["dispatch"].action is Action.RESET_PASSWORD
    assert delta["external_operation"] is not None
    assert delta["external_operation"].action is Action.RESET_PASSWORD
    assert delta["outcome"] is not None
    assert delta["outcome"].next_step is NextStep.EXECUTE_ACTION


def test_ambiguous_confirmation_invalidates_then_a_fresh_one_recovers() -> None:
    ambiguous = advance_turn(
        _autonomous_state(
            model_decision=make_decision(
                route=Route.CONTINUE,
                confirmation_observation=ConfirmationObservation.AMBIGUOUS,
            )
        )
    )
    assert ambiguous["confirmation"] is None
    # No prior mutation in this fixture, so no dispatch exists yet.
    assert ambiguous["dispatch"] is None
    assert ambiguous["goal"] is not None
    assert ambiguous["goal"].assistance_mode is AssistanceMode.AUTONOMOUS

    reissued = advance_turn(
        _autonomous_state(
            confirmation=None,
            model_decision=make_decision(route=Route.CONTINUE, confirmation_request=True),
        )
    )
    assert reissued["confirmation"] is not None
    assert reissued["dispatch"] is None

    authorized = advance_turn(
        _autonomous_state(
            model_decision=make_decision(
                route=Route.CONTINUE,
                confirmation_observation=ConfirmationObservation.AFFIRMATIVE,
            )
        )
    )
    assert authorized["dispatch"] is not None
    assert authorized["dispatch"].action is Action.RESET_PASSWORD


def test_explicit_guided_switch_still_changes_the_mode() -> None:
    delta = advance_turn(
        _autonomous_state(
            model_decision=make_decision(
                route=Route.CONTINUE,
                assistance_mode=AssistanceMode.GUIDED,
            )
        )
    )
    assert delta["goal"] is not None
    assert delta["goal"].assistance_mode is AssistanceMode.GUIDED
    assert delta["confirmation"] is None
    assert delta["dispatch"] is None


# --- F0: exact signatures from E2E Ivr01-1790609256.7975 ----------------------


def test_f0_correct_autonomous_decision_opens_the_challenge() -> None:
    """The expected decision (AUTONOMOUS + confirmation_request) is accepted:
    challenge opened, no violations, LISTEN, no dispatch."""
    delta = advance_turn(
        _autonomous_state(
            goal=make_goal(Action.RESET_PASSWORD, assistance_mode=AssistanceMode.UNDECIDED),
            confirmation=None,
            model_decision=make_decision(
                route=Route.CONTINUE,
                goal={"intent": "REQUEST", "action": "RESET_PASSWORD"},
                assistance_mode=AssistanceMode.AUTONOMOUS,
                confirmation_request=True,
            ),
        )
    )
    assert delta["goal"] is not None
    assert delta["goal"].assistance_mode is AssistanceMode.AUTONOMOUS
    assert delta["confirmation"] is not None
    assert delta["confirmation"].action is Action.RESET_PASSWORD
    assert delta["outcome"] is not None
    assert delta["outcome"].violations == ()
    assert delta["outcome"].next_step is NextStep.LISTEN
    assert delta["dispatch"] is None


def test_f0_failure_signature_affirmation_without_mode() -> None:
    """The observed failure: the model affirmed without proposing AUTONOMOUS,
    so the mode stays UNDECIDED, the guard blocks and the message is the safe
    fallback with the exact violation."""
    delta = advance_turn(
        _autonomous_state(
            goal=make_goal(Action.RESET_PASSWORD, assistance_mode=AssistanceMode.UNDECIDED),
            confirmation=None,
            model_decision=make_decision(
                route=Route.CONTINUE,
                message="No puedo confirmar eso en este momento.",
                confirmation_observation=ConfirmationObservation.AFFIRMATIVE,
            ),
        )
    )
    outcome = delta["outcome"]
    assert outcome is not None
    assert outcome.message == SAFE_FALLBACK_MESSAGE
    assert "affirmation without an active challenge" in outcome.violations
    assert delta["confirmation"] is None
    assert delta["goal"] is not None
    assert delta["goal"].assistance_mode is AssistanceMode.UNDECIDED
    assert delta["dispatch"] is None


def test_f0_claims_are_not_action_scoped_for_operation_succeeded() -> None:
    """Latent risk pinned, not fixed here: a historical UNLOCK confirmed backs
    OPERATION_SUCCEEDED even for an active RESET goal, while RESET_CONFIRMED
    stays unbacked."""
    succeeded = advance_turn(
        _autonomous_state(
            dispatch=make_dispatch(
                Action.UNLOCK_ACCOUNT,
                revision=1,
                operation_id="operation-1",
                challenge_id="unlock-challenge",
            ),
            external_operation=make_operation(
                Action.UNLOCK_ACCOUNT, OperationStatus.CONFIRMED, operation_id="operation-1"
            ),
            model_decision=make_decision(
                route=Route.CONTINUE,
                claims=[{"kind": "OPERATION_SUCCEEDED"}],
            ),
        )
    )
    assert succeeded["outcome"] is not None
    assert succeeded["outcome"].violations == ()

    reset_confirmed = advance_turn(
        _autonomous_state(
            model_decision=make_decision(
                route=Route.CONTINUE,
                claims=[{"kind": "RESET_CONFIRMED"}],
            )
        )
    )
    assert reset_confirmed["outcome"] is not None
    assert "unbacked claim RESET_CONFIRMED" in reset_confirmed["outcome"].violations
